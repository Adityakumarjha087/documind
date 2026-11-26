"""Seed a demo account with realistic documents, conversations, analytics history and an eval run.

Usage:  python -m app.seed            (idempotent: skips if the demo user exists)
Login:  demo@documind.dev / demo-password-123
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker
from app.llm.base import ChatMessage
from app.llm.factory import get_embedder, get_llm
from app.llm.pricing import estimate_cost
from app.logs import configure_logging, get_logger
from app.models import (
    Conversation,
    Document,
    EvalRun,
    Feedback,
    Membership,
    Message,
    QueryLog,
    Role,
    User,
    Workspace,
)
from app.rag.pipeline import AnswerOutcome, answer_question
from app.rag.rerank import get_reranker
from app.security import hash_password
from app.services.evals import run_eval
from app.services.ingestion import ingest_document
from app.storage import get_storage

log = get_logger("seed")
DATA = Path(__file__).parent / "seed_data"
DEMO_EMAIL = "demo@documind.dev"
DEMO_PASSWORD = "demo-password-123"

EVAL_SET = [
    {
        "question": "How many days of paid time off do full-time employees get per year?",
        "ground_truth": "Full-time employees accrue 21 days of paid time off per year.",
    },
    {
        "question": "When must security incidents be reported?",
        "ground_truth": "Security incidents must be reported within one hour of discovery.",
    },
    {
        "question": "How much does the Growth plan cost?",
        "ground_truth": "The Growth plan costs 59 USD per user per month.",
    },
    {
        "question": "How long is the free trial?",
        "ground_truth": "New workspaces get a 14-day free trial of the Growth plan.",
    },
    {
        "question": "What is the on-call stipend?",
        "ground_truth": "On-call engineers receive a stipend of 300 USD per week.",
    },
    {
        "question": "What is the daily meal allowance during business travel?",
        "ground_truth": "The daily meal allowance during business travel is 60 USD.",
    },
    {"question": "Who won the 1998 football world cup?", "ground_truth": None},
]

SAMPLE_QUESTIONS = [
    "How many remote days per week are allowed?",
    "What is the parental leave for primary caregivers?",
    "Do I need the VPN on public Wi-Fi?",
    "How often do dashboards refresh on the Starter plan?",
    "When are production deployments?",
    "How long are query results cached?",
    "What is the home office budget?",
    "What password length is required?",
]


async def seed() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    sm = get_sessionmaker()
    async with sm() as session:
        if (
            await session.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one_or_none():
            log.info("seed_skipped_demo_user_exists")
            return
        demo = User(
            email=DEMO_EMAIL, full_name="Demo Admin", password_hash=hash_password(DEMO_PASSWORD)
        )
        analyst = User(
            email="analyst@documind.dev",
            full_name="Riya Analyst",
            password_hash=hash_password(DEMO_PASSWORD),
        )
        ws = Workspace(name="Acme Corp Knowledge Base")
        other = Workspace(name="Personal Notes")
        session.add_all([demo, analyst, ws, other])
        await session.flush()
        session.add_all(
            [
                Membership(user_id=demo.id, workspace_id=ws.id, role=Role.owner),
                Membership(user_id=analyst.id, workspace_id=ws.id, role=Role.member),
                Membership(user_id=demo.id, workspace_id=other.id, role=Role.owner),
            ]
        )
        doc_ids = []
        for i, path in enumerate(sorted(DATA.glob("*.md"))):
            doc_id = uuid.uuid4()
            key = f"{ws.id}/{doc_id}/{path.name}"
            await get_storage().put(key, path.read_bytes(), "text/markdown")
            session.add(
                Document(
                    id=doc_id,
                    workspace_id=ws.id,
                    uploaded_by=demo.id,
                    title=path.read_text().splitlines()[0].lstrip("# ").strip(),
                    source_type="md",
                    source_uri=key,
                    mime_type="text/markdown",
                    size_bytes=path.stat().st_size,
                    chunk_strategy="semantic" if i % 2 else "recursive",
                    meta={"filename": path.name},
                )
            )
            doc_ids.append(doc_id)
        await session.commit()
        ws_id, demo_id = ws.id, demo.id

    for doc_id in doc_ids:
        await ingest_document(sm, doc_id)
    log.info("seed_documents_ingested", count=len(doc_ids))

    llm, embedder, reranker = get_llm(), get_embedder(), get_reranker()
    rng = random.Random(42)
    async with sm() as session:
        # Two real conversations through the live pipeline.
        for title, turns in [
            ("Remote work & equipment", ["Can I work remotely?", "and what equipment do I get?"]),
            ("Product pricing", ["What plans does Acme Analytics offer?"]),
        ]:
            conv = Conversation(workspace_id=ws_id, user_id=demo_id, title=title)
            session.add(conv)
            await session.flush()
            history: list[ChatMessage] = []
            for q in turns:
                outcome = AnswerOutcome()
                async for _ in answer_question(
                    session, ws_id, q, history, llm, embedder, reranker, outcome
                ):
                    pass
                session.add(Message(conversation_id=conv.id, role="user", content=q))
                msg = Message(
                    conversation_id=conv.id,
                    role="assistant",
                    content=outcome.answer,
                    rewritten_query=outcome.rewritten_query,
                    citations=outcome.citations,
                    grounded=outcome.grounded,
                )
                session.add(msg)
                await session.flush()
                session.add(
                    Feedback(message_id=msg.id, user_id=demo_id, workspace_id=ws_id, rating=1)
                )
                history += [ChatMessage("user", q), ChatMessage("assistant", outcome.answer)]

        # 14 days of synthetic query history for the analytics dashboard.
        now = datetime.now(UTC)
        for day in range(14):
            for _ in range(rng.randint(3, 18)):
                pt, ct = rng.randint(900, 2600), rng.randint(80, 420)
                model = "claude-opus-5-5"
                session.add(
                    QueryLog(
                        workspace_id=ws_id,
                        user_id=demo_id,
                        query=rng.choice(SAMPLE_QUESTIONS),
                        provider="anthropic",
                        model=model,
                        latency_ms=rng.randint(700, 4200),
                        retrieval_ms=rng.randint(15, 90),
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        cost_usd=estimate_cost(model, pt, ct),
                        grounded=rng.random() > 0.08,
                        created_at=now - timedelta(days=day, minutes=rng.randint(0, 600)),
                    )
                )
        run = EvalRun(
            workspace_id=ws_id,
            name="Baseline (hybrid + lexical rerank)",
            config={"judge": "heuristic", "questions": EVAL_SET},
        )
        session.add(run)
        await session.commit()
        run_id = run.id
    await run_eval(sm, run_id)
    log.info("seed_complete", login=DEMO_EMAIL, password=DEMO_PASSWORD)


def main() -> None:
    async def _run() -> None:
        try:
            await seed()
        finally:
            await dispose_engine()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
