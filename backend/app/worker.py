"""Celery worker: ingestion and evaluation jobs."""

from __future__ import annotations

import asyncio
import uuid

from celery import Celery

from app.config import get_settings
from app.logs import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

celery_app = Celery("documind", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    task_time_limit=60 * 30,
)


def _run(coro_factory):  # type: ignore[no-untyped-def]
    """Each task gets a fresh event loop and engine (engines are loop-bound)."""
    from app.db import dispose_engine, get_sessionmaker

    async def runner() -> None:
        try:
            await coro_factory(get_sessionmaker())
        finally:
            await dispose_engine()

    asyncio.run(runner())


@celery_app.task(name="documind.ingest_document", bind=True, max_retries=2)
def ingest_document_task(self, document_id: str) -> None:  # type: ignore[no-untyped-def]
    from app.services.ingestion import ingest_document

    _run(lambda sm: ingest_document(sm, uuid.UUID(document_id)))


@celery_app.task(name="documind.run_eval")
def run_eval_task(run_id: str) -> None:
    from app.services.evals import run_eval

    _run(lambda sm: run_eval(sm, uuid.UUID(run_id)))
