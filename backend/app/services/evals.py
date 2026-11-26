"""Run an evaluation set through the live RAG pipeline and score it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.factory import get_embedder, get_llm
from app.logs import get_logger
from app.models import EvalRun
from app.rag.evaluation import EvalSample, score_sample, summarize
from app.rag.pipeline import AnswerOutcome, answer_question
from app.rag.rerank import get_reranker

log = get_logger(__name__)


async def run_eval(sm: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> None:
    async with sm() as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            return
        try:
            llm, embedder, reranker = get_llm(), get_embedder(), get_reranker()
            judge = llm if run.config.get("judge") == "llm" and llm.name != "fake" else None
            results: list[dict[str, Any]] = []
            for item in run.config.get("questions", []):
                outcome = AnswerOutcome()
                async for _ in answer_question(
                    session,
                    run.workspace_id,
                    item["question"],
                    [],
                    llm,
                    embedder,
                    reranker,
                    outcome,
                ):
                    pass
                sample = EvalSample(
                    item["question"], outcome.answer, outcome.contexts, item.get("ground_truth")
                )
                scores = await score_sample(sample, embedder, judge)
                results.append(
                    {
                        "question": item["question"],
                        "ground_truth": item.get("ground_truth"),
                        "answer": outcome.answer,
                        "grounded": outcome.grounded,
                        "num_contexts": len(outcome.contexts),
                        "latency_ms": outcome.latency_ms,
                        **scores,
                    }
                )
            run.results = results
            run.summary = summarize(results)
            run.status = "completed"
        except Exception as e:
            log.exception("eval_failed", run_id=str(run_id))
            run.status = "failed"
            run.summary = {}
            run.config = {**run.config, "error": str(e)}
        run.finished_at = datetime.now(UTC)
        await session.commit()
