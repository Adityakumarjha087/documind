"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import get_sessionmaker

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> JSONResponse:
    s = get_settings()
    checks: dict[str, Any] = {}
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e.__class__.__name__}"
    if s.ingestion_mode == "celery":
        try:
            r = aioredis.from_url(s.redis_url, socket_connect_timeout=1)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e.__class__.__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {
            "status": "ok" if ok else "degraded",
            "checks": checks,
            "llm_provider": s.llm_provider,
            "embedding_provider": s.embedding_provider,
        },
        status_code=200 if ok else 503,
    )
