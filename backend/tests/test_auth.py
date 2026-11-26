from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import register


async def test_register_login_me(client: AsyncClient) -> None:
    acct = await register(client, "ada@example.com")
    r = await client.get("/api/auth/me", headers=acct.headers)
    assert r.status_code == 200
    assert r.json()["email"] == "ada@example.com"

    r = await client.post(
        "/api/auth/login", json={"email": "ADA@example.com", "password": "s3cret-pass"}
    )
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"


async def test_register_duplicate_and_validation(client: AsyncClient) -> None:
    await register(client, "dup@example.com")
    r = await client.post(
        "/api/auth/register",
        json={"email": "dup@example.com", "password": "s3cret-pass", "full_name": "X"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"
    r = await client.post(
        "/api/auth/register", json={"email": "bad", "password": "x", "full_name": ""}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_login_wrong_password(client: AsyncClient) -> None:
    await register(client, "eve@example.com")
    r = await client.post(
        "/api/auth/login", json={"email": "eve@example.com", "password": "nope-nope"}
    )
    assert r.status_code == 401


async def test_protected_requires_token(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401
    r = await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


async def test_refresh_rotation_and_reuse_detection(client: AsyncClient) -> None:
    acct = await register(client)
    old = acct.tokens["refresh_token"]
    r = await client.post("/api/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()["refresh_token"]
    assert new != old
    # Reusing the rotated token revokes the whole family, including the new token.
    r = await client.post("/api/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 401
    r = await client.post("/api/auth/refresh", json={"refresh_token": new})
    assert r.status_code == 401


async def test_logout_revokes_refresh(client: AsyncClient) -> None:
    acct = await register(client)
    rt = acct.tokens["refresh_token"]
    assert (await client.post("/api/auth/logout", json={"refresh_token": rt})).status_code == 204
    assert (await client.post("/api/auth/refresh", json={"refresh_token": rt})).status_code == 401
    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": "unknown"})
    ).status_code == 401
