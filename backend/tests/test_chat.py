from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient

from tests.conftest import Account, upload


def parse_sse(body: str) -> list[tuple[str, Any]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def ask(client: AsyncClient, acct: Account, conv_id: str, q: str) -> list[tuple[str, Any]]:
    r = await client.post(
        f"/api/workspaces/{acct.workspace_id}/conversations/{conv_id}/messages",
        json={"content": q},
        headers=acct.headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)


async def new_conv(client: AsyncClient, acct: Account) -> str:
    r = await client.post(
        f"/api/workspaces/{acct.workspace_id}/conversations", json={}, headers=acct.headers
    )
    assert r.status_code == 201
    return str(r.json()["id"])


async def test_streaming_answer_with_citations(client: AsyncClient, account: Account) -> None:
    await upload(client, account)
    conv = await new_conv(client, account)
    events = await ask(
        client, account, conv, "How much is the internet stipend for remote employees?"
    )
    kinds = [e for e, _ in events]
    assert kinds[0] == "sources" and kinds[-1] == "done" and "token" in kinds
    answer = "".join(d["text"] for e, d in events if e == "token")
    assert "50 USD" in answer
    done = events[-1][1]
    assert done["grounded"] is True
    assert any(c["cited"] for c in done["citations"])
    assert done["usage"]["completion_tokens"] > 0

    detail = (
        await client.get(
            f"/api/workspaces/{account.workspace_id}/conversations/{conv}", headers=account.headers
        )
    ).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["title"].startswith("How much")
    assert detail["messages"][1]["citations"]


async def test_follow_up_is_rewritten(client: AsyncClient, account: Account) -> None:
    await upload(client, account)
    conv = await new_conv(client, account)
    await ask(
        client, account, conv, "What equipment does the company provide for remote employees?"
    )
    events = await ask(client, account, conv, "and what about security?")
    rewrite = [d for e, d in events if e == "rewrite"]
    assert rewrite and "security" in rewrite[0]["query"].lower()
    answer = "".join(d["text"] for e, d in events if e == "token")
    assert "VPN" in answer


async def test_guardrail_refuses_without_context(client: AsyncClient, account: Account) -> None:
    await upload(client, account)
    conv = await new_conv(client, account)
    events = await ask(client, account, conv, "What is the boiling point of mercury on Jupiter?")
    done = events[-1][1]
    assert done["grounded"] is False
    answer = "".join(d["text"] for e, d in events if e == "token")
    assert "don't have enough information" in answer


async def test_empty_workspace_refuses(client: AsyncClient, account: Account) -> None:
    conv = await new_conv(client, account)
    events = await ask(client, account, conv, "What is the leave policy?")
    assert events[-1][1]["grounded"] is False


async def test_feedback_and_conversation_management(client: AsyncClient, account: Account) -> None:
    await upload(client, account)
    conv = await new_conv(client, account)
    events = await ask(client, account, conv, "Who approves remote work schedules?")
    msg_id = events[-1][1]["message_id"]
    user_msg_id = events[-1][1]["user_message_id"]
    base = f"/api/workspaces/{account.workspace_id}"
    assert (
        await client.put(
            f"{base}/messages/{msg_id}/feedback", json={"rating": 1}, headers=account.headers
        )
    ).status_code == 204
    assert (
        await client.put(
            f"{base}/messages/{msg_id}/feedback",
            json={"rating": -1, "comment": "meh"},
            headers=account.headers,
        )
    ).status_code == 204
    assert (
        await client.put(
            f"{base}/messages/{user_msg_id}/feedback", json={"rating": 1}, headers=account.headers
        )
    ).status_code == 404
    assert (
        await client.put(
            f"{base}/messages/{msg_id}/feedback", json={"rating": 5}, headers=account.headers
        )
    ).status_code == 422
    detail = (await client.get(f"{base}/conversations/{conv}", headers=account.headers)).json()
    assert detail["messages"][1]["feedback"] == -1

    analytics = (await client.get(f"{base}/analytics?days=7", headers=account.headers)).json()
    assert analytics["total_queries"] == 1
    assert analytics["feedback_down"] == 1
    assert analytics["documents"] == 1 and analytics["chunks"] >= 1
    assert len(analytics["daily"]) == 7 and analytics["daily"][-1]["queries"] == 1

    assert len((await client.get(f"{base}/conversations", headers=account.headers)).json()) == 1
    assert (
        await client.delete(f"{base}/conversations/{conv}", headers=account.headers)
    ).status_code == 204
    assert (
        await client.get(f"{base}/conversations/{conv}", headers=account.headers)
    ).status_code == 404
