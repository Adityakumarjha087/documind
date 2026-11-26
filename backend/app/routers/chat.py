"""Conversations and streaming chat (Server-Sent Events) with citations and feedback."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import get_sessionmaker
from app.deps import MemberCtx, SessionDep
from app.errors import AppError, NotFound
from app.llm.base import ChatMessage
from app.llm.factory import get_embedder, get_llm
from app.llm.pricing import estimate_cost
from app.logs import get_logger
from app.models import Conversation, Feedback, Message, QueryLog
from app.rag.pipeline import AnswerOutcome, answer_question
from app.rag.rerank import get_reranker
from app.schemas import (
    AskIn,
    ConversationDetail,
    ConversationIn,
    ConversationOut,
    FeedbackIn,
    MessageOut,
)

log = get_logger(__name__)
router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["chat"])


async def _get_conv(
    session: SessionDep, ctx: MemberCtx, conversation_id: uuid.UUID, with_messages: bool = False
) -> Conversation:
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.workspace_id == ctx.workspace.id,
        Conversation.user_id == ctx.user.id,
    )
    if with_messages:
        stmt = stmt.options(selectinload(Conversation.messages))
    conv = (await session.execute(stmt)).scalar_one_or_none()
    if conv is None:
        raise NotFound("Conversation not found")
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    ctx: MemberCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Conversation]:
    rows = await session.execute(
        select(Conversation)
        .where(Conversation.workspace_id == ctx.workspace.id, Conversation.user_id == ctx.user.id)
        .order_by(Conversation.created_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars())


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationIn, ctx: MemberCtx, session: SessionDep
) -> Conversation:
    conv = Conversation(
        workspace_id=ctx.workspace.id, user_id=ctx.user.id, title=body.title or "New conversation"
    )
    session.add(conv)
    await session.commit()
    return conv


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, ctx: MemberCtx, session: SessionDep
) -> ConversationDetail:
    conv = await _get_conv(session, ctx, conversation_id, with_messages=True)
    ids = [m.id for m in conv.messages]
    ratings: dict[uuid.UUID, int] = {}
    if ids:
        rows = await session.execute(
            select(Feedback.message_id, Feedback.rating).where(
                Feedback.message_id.in_(ids), Feedback.user_id == ctx.user.id
            )
        )
        ratings = {mid: r for mid, r in rows.all()}
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        messages=[
            MessageOut.model_validate(m).model_copy(update={"feedback": ratings.get(m.id)})
            for m in conv.messages
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, ctx: MemberCtx, session: SessionDep
) -> None:
    conv = await _get_conv(session, ctx, conversation_id)
    await session.delete(conv)
    await session.commit()


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "SSE stream: rewrite, sources, token, done, error",
        }
    },
)
async def ask(
    conversation_id: uuid.UUID, body: AskIn, ctx: MemberCtx, session: SessionDep, request: Request
) -> StreamingResponse:
    conv = await _get_conv(session, ctx, conversation_id, with_messages=True)
    history = [
        ChatMessage("assistant" if m.role == "assistant" else "user", m.content)
        for m in conv.messages
    ]
    user_msg = Message(conversation_id=conv.id, role="user", content=body.content)
    session.add(user_msg)
    if not history:
        conv.title = body.content[:80]
    await session.commit()

    workspace_id, user_id = ctx.workspace.id, ctx.user.id
    llm, embedder, reranker = get_llm(), get_embedder(), get_reranker()

    async def stream() -> AsyncIterator[str]:
        outcome = AnswerOutcome()
        # The request-scoped session closes when the handler returns; use a dedicated one.
        async with get_sessionmaker()() as s:
            try:
                async for event in answer_question(
                    s,
                    workspace_id,
                    body.content,
                    history,
                    llm,
                    embedder,
                    reranker,
                    outcome,
                    document_ids=body.document_ids,
                ):
                    if await request.is_disconnected():
                        log.info("client_disconnected", conversation_id=str(conversation_id))
                        return
                    yield _sse(event["type"], {k: v for k, v in event.items() if k != "type"})
            except AppError as e:
                yield _sse("error", {"code": e.code, "message": e.message})
                return
            except Exception:
                log.exception("chat_stream_failed")
                yield _sse(
                    "error", {"code": "internal_error", "message": "Answer generation failed"}
                )
                return

            msg = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=outcome.answer,
                rewritten_query=outcome.rewritten_query,
                citations=outcome.citations,
                grounded=outcome.grounded,
            )
            s.add(msg)
            s.add(
                QueryLog(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    query=body.content,
                    provider=llm.name,
                    model=outcome.model or llm.model,
                    latency_ms=outcome.latency_ms,
                    retrieval_ms=outcome.retrieval_ms,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    cost_usd=estimate_cost(
                        outcome.model or llm.model, outcome.prompt_tokens, outcome.completion_tokens
                    ),
                    grounded=outcome.grounded,
                )
            )
            await s.commit()
            yield _sse(
                "done",
                {
                    "message_id": str(msg.id),
                    "user_message_id": str(user_msg.id),
                    "grounded": outcome.grounded,
                    "citations": outcome.citations,
                    "usage": {
                        "prompt_tokens": outcome.prompt_tokens,
                        "completion_tokens": outcome.completion_tokens,
                    },
                    "latency_ms": outcome.latency_ms,
                },
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.put("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def give_feedback(
    message_id: uuid.UUID, body: FeedbackIn, ctx: MemberCtx, session: SessionDep
) -> None:
    row = (
        await session.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Conversation.workspace_id == ctx.workspace.id,
                Conversation.user_id == ctx.user.id,
                Message.role == "assistant",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Message not found")
    fb = (
        await session.execute(
            select(Feedback).where(
                Feedback.message_id == message_id, Feedback.user_id == ctx.user.id
            )
        )
    ).scalar_one_or_none()
    if fb is None:
        session.add(
            Feedback(
                message_id=message_id,
                user_id=ctx.user.id,
                workspace_id=ctx.workspace.id,
                rating=body.rating,
                comment=body.comment,
            )
        )
    else:
        fb.rating, fb.comment = body.rating, body.comment
    await session.commit()
