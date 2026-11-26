from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.llm import factory
from app.rag.rerank import Candidate, CohereReranker, LexicalReranker
from app.ratelimit import RateLimiter, RateLimitMiddleware
from app.security import create_access_token, decode_access_token, hash_password, verify_password
from app.storage import LocalStorage


def test_settings_parse_cors_csv() -> None:
    s = Settings(cors_origins="http://a.com, http://b.com")  # type: ignore[arg-type]
    assert s.cors_origins == ["http://a.com", "http://b.com"]
    assert "+psycopg" in s.sync_database_url


def test_settings_from_env_csv_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com,http://b.com")
    monkeypatch.setenv("LLM_MODEL", "")
    s = Settings()
    assert s.cors_origins == ["http://a.com", "http://b.com"]
    assert s.llm_model is None
    monkeypatch.setenv("CORS_ORIGINS", '["http://c.com"]')
    assert Settings().cors_origins == ["http://c.com"]


def test_password_and_jwt() -> None:
    h = hash_password("pw-123456")
    assert verify_password("pw-123456", h) and not verify_password("x", h)
    assert not verify_password("x", "not-a-hash")
    uid = uuid.uuid4()
    assert decode_access_token(create_access_token(uid)) == uid


async def test_local_storage_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    st = LocalStorage(str(tmp_path))
    await st.put("a/b.txt", b"data")
    assert await st.get("a/b.txt") == b"data"
    await st.delete("a/b.txt")
    with pytest.raises(ValueError):
        await st.put("../escape.txt", b"x")


async def test_rate_limiter_memory_and_middleware(monkeypatch: pytest.MonkeyPatch) -> None:
    rl = RateLimiter(None)
    results = [await rl.hit("k", 2, 60) for _ in range(3)]
    assert [r[0] for r in results] == [True, True, False]

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_AUTH_REQUESTS", "2")
    get_settings.cache_clear()
    try:
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(None))

        @app.post("/api/auth/login")
        async def login() -> dict[str, str]:
            return {"ok": "yes"}

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"ok": "yes"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = [(await c.post("/api/auth/login")).status_code for _ in range(3)]
            assert codes == [200, 200, 429]
            assert (await c.get("/health")).status_code == 200
    finally:
        get_settings.cache_clear()


async def test_unhandled_errors_are_wrapped() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        r = await c.get("/boom")
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "internal_error"
        assert "secret" not in r.text
        assert (await c.get("/missing")).json()["error"]["code"] == "not_found"


@respx.mock
async def test_cohere_reranker_and_fallback() -> None:
    route = respx.post("https://api.cohere.com/v2/rerank")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ]
            },
        )
    )
    cands = [Candidate("a", "x", 0.1), Candidate("b", "vpn policy", 0.1)]
    rr = CohereReranker("key", LexicalReranker())
    assert await rr.rerank("vpn", cands) == [0.1, 0.9]
    route.mock(return_value=httpx.Response(500))
    assert len(await rr.rerank("vpn", cands)) == 2
    assert await rr.rerank("vpn", []) == []


def test_factory_selects_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = {
        "anthropic": "AnthropicLLM",
        "openai": "OpenAILLM",
        "ollama": "OllamaLLM",
        "fake": "FakeLLM",
    }
    try:
        for provider, cls in cases.items():
            monkeypatch.setenv("LLM_PROVIDER", provider)
            monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
            monkeypatch.setenv("OPENAI_API_KEY", "x")
            get_settings.cache_clear()
            factory.get_llm.cache_clear()
            assert type(factory.get_llm()).__name__ == cls
        for provider, cls in {
            "openai": "OpenAIEmbedder",
            "ollama": "OllamaEmbedder",
            "hash": "HashEmbedder",
        }.items():
            monkeypatch.setenv("EMBEDDING_PROVIDER", provider)
            get_settings.cache_clear()
            factory.get_embedder.cache_clear()
            assert type(factory.get_embedder()).__name__ == cls
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        factory.get_llm.cache_clear()
        factory.get_embedder.cache_clear()


async def test_health_endpoints(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    r = await client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"
    r = await client.get("/openapi.json")
    assert r.status_code == 200 and "/api/workspaces/{workspace_id}/search" in r.json()["paths"]
    assert "x-request-id" in {k.lower() for k in r.headers}


def test_hosted_postgres_url_normalisation() -> None:
    s = Settings(
        database_url="postgresql://u:p@ep-x.neon.tech/documind?sslmode=require&channel_binding=require"
    )
    assert s.database_url.startswith("postgresql+asyncpg://")
    url, args = s.async_engine_args()
    assert "sslmode" not in url and "channel_binding" not in url
    assert args == {"ssl": "require"}
    assert (
        s.sync_database_url.startswith("postgresql+psycopg://")
        and "sslmode=require" in s.sync_database_url
    )
    plain = Settings(database_url="postgres://u:p@localhost:5432/db")
    assert plain.async_engine_args() == ("postgresql+asyncpg://u:p@localhost:5432/db", {})


def test_demo_mode_allows_fake_llm_in_production() -> None:
    ok = Settings(
        environment="production", jwt_secret="x" * 40, llm_provider="fake", demo_mode=True
    )
    assert ok.demo_mode
    with pytest.raises(ValueError, match="fake"):
        Settings(environment="production", jwt_secret="x" * 40, llm_provider="fake")
