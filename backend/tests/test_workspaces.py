from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import register


async def test_workspace_crud_and_roles(client: AsyncClient) -> None:
    owner = await register(client, "owner@example.com")
    member = await register(client, "member@example.com", "Bob Member")
    ws = owner.workspace_id

    r = await client.post("/api/workspaces", json={"name": "Second"}, headers=owner.headers)
    assert r.status_code == 201 and r.json()["role"] == "owner"
    assert len((await client.get("/api/workspaces", headers=owner.headers)).json()) == 2

    # Non-members cannot see the workspace (404, not 403).
    assert (await client.get(f"/api/workspaces/{ws}", headers=member.headers)).status_code == 404

    r = await client.post(
        f"/api/workspaces/{ws}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner.headers,
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/workspaces/{ws}/members", json={"email": "member@example.com"}, headers=owner.headers
    )
    assert r.status_code == 409
    r = await client.post(
        f"/api/workspaces/{ws}/members", json={"email": "ghost@example.com"}, headers=owner.headers
    )
    assert r.status_code == 404

    assert (await client.get(f"/api/workspaces/{ws}", headers=member.headers)).json()[
        "role"
    ] == "member"
    # Members can't rename or manage members.
    assert (
        await client.patch(f"/api/workspaces/{ws}", json={"name": "x"}, headers=member.headers)
    ).status_code == 403
    members = (await client.get(f"/api/workspaces/{ws}/members", headers=member.headers)).json()
    assert {m["email"] for m in members} == {"owner@example.com", "member@example.com"}

    member_id = next(m["user_id"] for m in members if m["email"] == "member@example.com")
    owner_id = next(m["user_id"] for m in members if m["email"] == "owner@example.com")
    r = await client.patch(
        f"/api/workspaces/{ws}/members/{member_id}", json={"role": "admin"}, headers=owner.headers
    )
    assert r.status_code == 200 and r.json()["role"] == "admin"
    # Admin can rename but can't demote the owner.
    assert (
        await client.patch(
            f"/api/workspaces/{ws}", json={"name": "Renamed"}, headers=member.headers
        )
    ).json()["name"] == "Renamed"
    r = await client.patch(
        f"/api/workspaces/{ws}/members/{owner_id}", json={"role": "member"}, headers=member.headers
    )
    assert r.status_code == 403
    # Last owner can't demote themselves.
    r = await client.patch(
        f"/api/workspaces/{ws}/members/{owner_id}", json={"role": "admin"}, headers=owner.headers
    )
    assert r.status_code == 409
    r = await client.delete(f"/api/workspaces/{ws}/members/{owner_id}", headers=owner.headers)
    assert r.status_code == 409
    # Admin cannot delete workspace; member can leave.
    assert (await client.delete(f"/api/workspaces/{ws}", headers=member.headers)).status_code == 403
    assert (
        await client.delete(f"/api/workspaces/{ws}/members/{member_id}", headers=member.headers)
    ).status_code == 204
    assert (await client.delete(f"/api/workspaces/{ws}", headers=owner.headers)).status_code == 204
