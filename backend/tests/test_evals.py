from __future__ import annotations

from httpx import AsyncClient

from app.services import jobs
from tests.conftest import Account, register, upload


async def test_eval_run_produces_ragas_metrics(client: AsyncClient, account: Account) -> None:
    await upload(client, account)
    base = f"/api/workspaces/{account.workspace_id}/evals"
    body = {
        "name": "smoke",
        "questions": [
            {
                "question": "How many days per week can employees work remotely?",
                "ground_truth": "Eligible employees can work remotely up to three days per week.",
            },
            {
                "question": "What must remote employees use on public Wi-Fi?",
                "ground_truth": "They must use the corporate VPN.",
            },
            {"question": "What is the capital of Mongolia?"},
        ],
    }
    r = await client.post(base, json=body, headers=account.headers)
    assert r.status_code == 202 and r.json()["status"] == "running"
    await jobs.drain()
    run = (await client.get(f"{base}/{r.json()['id']}", headers=account.headers)).json()
    assert run["status"] == "completed", run
    assert set(run["summary"]) >= {"faithfulness", "answer_relevancy", "context_precision"}
    assert run["summary"]["faithfulness"] > 0.5
    assert run["results"][2]["grounded"] is False
    assert len((await client.get(base, headers=account.headers)).json()) == 1


async def test_eval_requires_admin(client: AsyncClient, account: Account) -> None:
    member = await register(client, "m@example.com")
    await client.post(
        f"/api/workspaces/{account.workspace_id}/members",
        json={"email": "m@example.com"},
        headers=account.headers,
    )
    r = await client.post(
        f"/api/workspaces/{account.workspace_id}/evals",
        json={"questions": [{"question": "q"}]},
        headers=member.headers,
    )
    assert r.status_code == 403
    r = await client.get(
        f"/api/workspaces/{account.workspace_id}/analytics", headers=member.headers
    )
    assert r.status_code == 403
