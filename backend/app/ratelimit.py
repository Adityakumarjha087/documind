"""Fixed-window rate limiter middleware. Uses Redis when reachable, else in-process memory.

Redis makes limits consistent across API replicas; the in-memory fallback keeps local dev and
tests dependency-free.
"""

from __future__ import annotations

import time
from collections import defaultdict

import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.config import get_settings
from app.logs import get_logger

log = get_logger(__name__)

AUTH_PATHS = ("/api/auth/login", "/api/auth/register", "/api/auth/refresh")
EXEMPT_PATHS = ("/health", "/docs", "/openapi.json", "/redoc")


class RateLimiter:
    def __init__(self, redis_url: str | None) -> None:
        self._redis: aioredis.Redis | None = (
            aioredis.from_url(redis_url, socket_connect_timeout=0.5) if redis_url else None
        )
        self._redis_ok = redis_url is not None
        self._memory: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])

    async def hit(self, key: str, limit: int, window: int) -> tuple[bool, int, int]:
        """Return (allowed, remaining, reset_seconds)."""
        now = time.time()
        bucket = int(now // window)
        reset = int(window - (now % window))
        full_key = f"rl:{key}:{bucket}"
        count: int
        if self._redis is not None and self._redis_ok:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(full_key)
                pipe.expire(full_key, window)
                count = int((await pipe.execute())[0])
                return count <= limit, max(0, limit - count), reset
            except Exception:  # pragma: no cover - depends on infra
                log.warning("rate_limit_redis_unavailable_fallback_memory")
                self._redis_ok = False
        entry = self._memory[key]
        if entry[0] != bucket:
            entry[0], entry[1] = bucket, 0
        entry[1] += 1
        count = int(entry[1])
        return count <= limit, max(0, limit - count), reset


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        s = get_settings()
        path = request.url.path
        if not s.rate_limit_enabled or path.startswith(EXEMPT_PATHS) or request.method == "OPTIONS":
            return await call_next(request)
        client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )
        is_auth = path.startswith(AUTH_PATHS)
        limit = s.rate_limit_auth_requests if is_auth else s.rate_limit_requests
        key = f"{'auth' if is_auth else 'api'}:{client}"
        allowed, remaining, reset = await self.limiter.hit(key, limit, s.rate_limit_window_seconds)
        if not allowed:
            return JSONResponse(
                {"error": {"code": "rate_limited", "message": "Too many requests"}},
                status_code=429,
                headers={"Retry-After": str(reset)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
