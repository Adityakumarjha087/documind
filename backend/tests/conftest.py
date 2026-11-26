"""Test fixtures. Integration tests need Postgres+pgvector at TEST_DATABASE_URL
(default: the docker-compose dev database's ``documind_test`` DB)."""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from typing import Any

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://documind:documind@localhost:5442/documind_test"
)
os.environ.update(
    {
        "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
        "ENVIRONMENT": "test",
        "INGESTION_MODE": "inline",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_DIR": tempfile.mkdtemp(prefix="documind-test-"),
        "LLM_PROVIDER": "fake",
        "EMBEDDING_PROVIDER": "hash",
        "RATE_LIMIT_ENABLED": "false",
        "LOG_LEVEL": "WARNING",
    }
)

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command
from app.db import dispose_engine, get_sessionmaker
from app.main import create_app
from app.services import jobs

TABLES = [
    "feedback",
    "query_logs",
    "eval_runs",
    "messages",
    "conversations",
    "chunks",
    "documents",
    "memberships",
    "refresh_tokens",
    "workspaces",
    "users",
]


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> None:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean_db(migrated_db: None) -> AsyncIterator[None]:
    yield
    await jobs.drain()
    async with get_sessionmaker()() as s:
        await s.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
        await s.commit()


@pytest.fixture(scope="session", autouse=True)
async def _dispose() -> AsyncIterator[None]:
    yield
    await dispose_engine()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class Account:
    def __init__(self, tokens: dict[str, Any], workspace_id: str, email: str) -> None:
        self.tokens = tokens
        self.workspace_id = workspace_id
        self.email = email

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens['access_token']}"}


async def register(
    client: AsyncClient, email: str | None = None, name: str = "Ada Lovelace"
) -> Account:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": "s3cret-pass", "full_name": name}
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    ws = await client.get(
        "/api/workspaces", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    return Account(tokens, ws.json()[0]["id"], email)


@pytest.fixture
async def account(client: AsyncClient) -> Account:
    return await register(client)


SAMPLE_MD = b"""# Remote Work Policy

## Eligibility
Employees who have completed their probation period of 90 days are eligible to work remotely
up to three days per week. Managers must approve remote work schedules in the HR portal.

## Equipment
The company provides a laptop and a monthly internet stipend of 50 USD for remote employees.
Employees are responsible for keeping company equipment secure and updated.

## Security
Remote employees must connect through the corporate VPN when accessing internal systems.
Public Wi-Fi networks may only be used together with the VPN.
"""


async def upload(
    client: AsyncClient,
    acct: Account,
    name: str = "policy.md",
    data: bytes = SAMPLE_MD,
    strategy: str = "recursive",
) -> dict[str, Any]:
    r = await client.post(
        f"/api/workspaces/{acct.workspace_id}/documents",
        headers=acct.headers,
        files={"file": (name, data, "text/markdown")},
        data={"chunk_strategy": strategy},
    )
    assert r.status_code == 202, r.text
    await jobs.drain()
    doc = await client.get(
        f"/api/workspaces/{acct.workspace_id}/documents/{r.json()['id']}", headers=acct.headers
    )
    return doc.json()  # type: ignore[no-any-return]
