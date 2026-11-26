"""Workspace analytics for admins: volume, latency, tokens, cost, groundedness, feedback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import Date, cast, func, select

from app.deps import AdminCtx, SessionDep
from app.models import Chunk, Document, Feedback, QueryLog
from app.schemas import AnalyticsOut, DailyPoint

router = APIRouter(prefix="/api/workspaces/{workspace_id}/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsOut)
async def analytics(
    ctx: AdminCtx, session: SessionDep, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> AnalyticsOut:
    ws = ctx.workspace.id
    since = datetime.now(UTC) - timedelta(days=days)
    base = (QueryLog.workspace_id == ws, QueryLog.created_at >= since)

    totals = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.avg(QueryLog.latency_ms), 0),
                func.coalesce(func.percentile_cont(0.95).within_group(QueryLog.latency_ms), 0),
                func.coalesce(func.sum(QueryLog.prompt_tokens + QueryLog.completion_tokens), 0),
                func.coalesce(func.sum(QueryLog.cost_usd), 0.0),
                func.count().filter(QueryLog.grounded.is_(True)),
            ).where(*base)
        )
    ).one()
    total, avg_lat, p95, tokens, cost, grounded = totals

    day = cast(QueryLog.created_at, Date).label("day")
    daily_rows = await session.execute(
        select(
            day,
            func.count(),
            func.avg(QueryLog.latency_ms),
            func.sum(QueryLog.prompt_tokens),
            func.sum(QueryLog.completion_tokens),
            func.sum(QueryLog.cost_usd),
        )
        .where(*base)
        .group_by(day)
        .order_by(day)
    )
    by_day = {r[0]: r for r in daily_rows}
    daily = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now(UTC) - timedelta(days=i)).date()
        r = by_day.get(d)
        daily.append(
            DailyPoint(
                day=d.isoformat(),
                queries=int(r[1]) if r else 0,
                avg_latency_ms=round(float(r[2]), 1) if r else 0.0,
                prompt_tokens=int(r[3] or 0) if r else 0,
                completion_tokens=int(r[4] or 0) if r else 0,
                cost_usd=round(float(r[5] or 0), 6) if r else 0.0,
            )
        )

    fb = (
        await session.execute(
            select(
                func.count().filter(Feedback.rating > 0), func.count().filter(Feedback.rating < 0)
            ).where(Feedback.workspace_id == ws, Feedback.created_at >= since)
        )
    ).one()
    docs = await session.scalar(select(func.count()).where(Document.workspace_id == ws))
    chunks = await session.scalar(select(func.count()).where(Chunk.workspace_id == ws))

    return AnalyticsOut(
        days=days,
        total_queries=int(total),
        avg_latency_ms=round(float(avg_lat), 1),
        p95_latency_ms=round(float(p95), 1),
        total_tokens=int(tokens),
        total_cost_usd=round(float(cost), 6),
        grounded_rate=round(int(grounded) / int(total), 4) if total else 0.0,
        feedback_up=int(fb[0]),
        feedback_down=int(fb[1]),
        documents=int(docs or 0),
        chunks=int(chunks or 0),
        daily=daily,
    )
