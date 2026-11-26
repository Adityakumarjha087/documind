"""RAG answer pipeline: rewrite → retrieve → guardrail → stream answer → citations.

Yields transport-agnostic events; the chat router serialises them as Server-Sent Events.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.base import ChatMessage, EmbeddingProvider, LLMProvider, StreamResult
from app.logs import get_logger
from app.rag import prompts
from app.rag.rerank import Reranker
from app.rag.retrieval import RetrievedChunk, hybrid_retrieve

log = get_logger(__name__)
_CITE = re.compile(r"\[(\d+)\]")


@dataclass
class AnswerOutcome:
    answer: str = ""
    rewritten_query: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    grounded: bool = True
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    retrieval_ms: int = 0
    latency_ms: int = 0
    contexts: list[str] = field(default_factory=list)


def citation_payload(chunks: list[RetrievedChunk], answer: str) -> list[dict[str, Any]]:
    cited = {int(n) for n in _CITE.findall(answer)}
    return [
        {
            "index": i,
            "chunk_id": str(c.chunk_id),
            "document_id": str(c.document_id),
            "document_title": c.document_title,
            "page": c.page,
            "section": c.section,
            "snippet": c.content[:600],
            "score": round(c.score, 4),
            "cited": i in cited,
        }
        for i, c in enumerate(chunks, start=1)
    ]


async def rewrite_query(llm: LLMProvider, history: list[ChatMessage], question: str) -> str:
    if not history:
        return question
    try:
        rewritten = await llm.complete(
            prompts.REWRITE_SYSTEM,
            prompts.build_rewrite_messages(history, question),
            max_tokens=200,
        )
    except Exception:
        log.warning("query_rewrite_failed")
        return question
    rewritten = rewritten.strip().strip('"').strip()
    return rewritten if 0 < len(rewritten) < 1000 else question


async def answer_question(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    question: str,
    history: list[ChatMessage],
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    reranker: Reranker,
    outcome: AnswerOutcome,
    document_ids: list[uuid.UUID] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    s = get_settings()
    started = time.perf_counter()

    search_query = await rewrite_query(llm, history, question)
    if search_query != question:
        outcome.rewritten_query = search_query
        yield {"type": "rewrite", "query": search_query}

    t0 = time.perf_counter()
    retrieval = await hybrid_retrieve(
        session, workspace_id, search_query, embedder, reranker, document_ids=document_ids
    )
    outcome.retrieval_ms = int((time.perf_counter() - t0) * 1000)
    chunks = [c for c in retrieval.chunks if c.score >= s.min_relevance * 0.5]
    outcome.contexts = [c.content for c in chunks]

    # Guardrail: refuse rather than hallucinate when nothing relevant was retrieved.
    if not chunks or retrieval.best_score < s.min_relevance:
        outcome.grounded = False
        outcome.answer = prompts.INSUFFICIENT_CONTEXT_ANSWER
        outcome.citations = []
        yield {"type": "sources", "sources": []}
        yield {"type": "token", "text": outcome.answer}
        outcome.latency_ms = int((time.perf_counter() - started) * 1000)
        return

    yield {"type": "sources", "sources": citation_payload(chunks, "")}

    # The standalone (rewritten) question is unambiguous without history; history is kept for tone.
    messages = prompts.build_answer_messages(search_query, chunks, history)
    result = StreamResult()
    parts: list[str] = []
    async for delta in llm.stream(prompts.ANSWER_SYSTEM, messages, result):
        parts.append(delta)
        yield {"type": "token", "text": delta}

    outcome.answer = "".join(parts)
    outcome.citations = citation_payload(chunks, outcome.answer)
    outcome.prompt_tokens = result.usage.prompt_tokens
    outcome.completion_tokens = result.usage.completion_tokens
    outcome.model = result.model or llm.model
    outcome.latency_ms = int((time.perf_counter() - started) * 1000)
