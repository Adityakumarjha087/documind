"""Background job dispatch: Celery in deployments, in-process tasks for tests/simple dev."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from typing import Any

from app.config import get_settings
from app.db import get_sessionmaker

_background: set[asyncio.Task[None]] = set()


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


def enqueue_ingestion(document_id: uuid.UUID) -> None:
    if get_settings().ingestion_mode == "celery":
        from app.worker import ingest_document_task

        ingest_document_task.delay(str(document_id))
    else:
        from app.services.ingestion import ingest_document

        _spawn(ingest_document(get_sessionmaker(), document_id))


def enqueue_eval(run_id: uuid.UUID) -> None:
    if get_settings().ingestion_mode == "celery":
        from app.worker import run_eval_task

        run_eval_task.delay(str(run_id))
    else:
        from app.services.evals import run_eval

        _spawn(run_eval(get_sessionmaker(), run_id))


async def drain() -> None:
    """Await in-process background jobs (used by tests)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)
