from __future__ import annotations

from sqlalchemy import func, select

from app.db import get_sessionmaker
from app.models import Document, DocumentStatus, EvalRun, QueryLog
from app.seed import seed


async def test_seed_is_complete_and_idempotent() -> None:
    await seed()
    await seed()  # second run is a no-op
    async with get_sessionmaker()() as s:
        statuses = (await s.execute(select(Document.status))).scalars().all()
        assert len(statuses) == 4 and set(statuses) == {DocumentStatus.ready}
        run = (await s.execute(select(EvalRun))).scalar_one()
        assert run.status == "completed" and run.summary["faithfulness"] > 0.5
        assert (await s.scalar(select(func.count()).select_from(QueryLog))) > 40
