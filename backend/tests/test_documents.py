from __future__ import annotations

import io

import docx
from httpx import AsyncClient
from reportlab.pdfgen import canvas

from tests.conftest import Account, register, upload


def make_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setTitle("Expense Handbook")
    c.drawString(72, 750, "Travel expenses must be submitted within 30 days of the trip.")
    c.showPage()
    c.drawString(72, 750, "Meal allowances are capped at 60 USD per day during business travel.")
    c.save()
    return buf.getvalue()


def make_docx() -> bytes:
    d = docx.Document()
    d.add_heading("Onboarding Guide", 0)
    d.add_heading("First week", 1)
    d.add_paragraph("New hires meet their onboarding buddy on the first Monday morning.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


async def test_upload_markdown_ingests_and_chunks(client: AsyncClient, account: Account) -> None:
    doc = await upload(client, account)
    assert doc["status"] == "ready", doc
    assert doc["progress"] == 100
    assert doc["num_chunks"] >= 1
    assert doc["source_type"] == "md"
    chunks = (
        await client.get(
            f"/api/workspaces/{account.workspace_id}/documents/{doc['id']}/chunks",
            headers=account.headers,
        )
    ).json()
    assert {c["section"] for c in chunks} >= {"Eligibility", "Security"}
    one = await client.get(
        f"/api/workspaces/{account.workspace_id}/chunks/{chunks[0]['id']}", headers=account.headers
    )
    assert one.status_code == 200


async def test_upload_pdf_tracks_pages(client: AsyncClient, account: Account) -> None:
    r = await client.post(
        f"/api/workspaces/{account.workspace_id}/documents",
        headers=account.headers,
        files={"file": ("handbook.pdf", make_pdf(), "application/pdf")},
    )
    assert r.status_code == 202
    from app.services import jobs

    await jobs.drain()
    doc = (
        await client.get(
            f"/api/workspaces/{account.workspace_id}/documents/{r.json()['id']}",
            headers=account.headers,
        )
    ).json()
    assert doc["status"] == "ready" and doc["num_pages"] == 2
    chunks = (
        await client.get(
            f"/api/workspaces/{account.workspace_id}/documents/{doc['id']}/chunks?page=2",
            headers=account.headers,
        )
    ).json()
    assert chunks and all(c["page"] == 2 for c in chunks)


async def test_upload_docx_and_semantic_chunking(client: AsyncClient, account: Account) -> None:
    doc = await upload(client, account, "guide.docx", make_docx(), strategy="semantic")
    assert doc["status"] == "ready", doc
    assert doc["chunk_strategy"] == "semantic"


async def test_upload_rejects_bad_files(client: AsyncClient, account: Account) -> None:
    base = f"/api/workspaces/{account.workspace_id}/documents"
    r = await client.post(base, headers=account.headers, files={"file": ("x.exe", b"MZ", "x")})
    assert r.status_code == 422
    r = await client.post(base, headers=account.headers, files={"file": ("x.pdf", b"nope", "x")})
    assert r.status_code == 422
    r = await client.post(
        base, headers=account.headers, files={"file": ("x.txt", b"", "text/plain")}
    )
    assert r.status_code == 422


async def test_failed_ingestion_reports_error(client: AsyncClient, account: Account) -> None:
    doc = await upload(client, account, "blank.txt", b"   \n  ")
    assert doc["status"] == "failed"
    assert "empty" in doc["error"].lower()


async def test_url_ingest_blocks_private_addresses(client: AsyncClient, account: Account) -> None:
    r = await client.post(
        f"/api/workspaces/{account.workspace_id}/documents/url",
        json={"url": "http://127.0.0.1:8000/secret"},
        headers=account.headers,
    )
    assert r.status_code == 422


async def test_list_filter_reindex_delete(client: AsyncClient, account: Account) -> None:
    doc = await upload(client, account)
    base = f"/api/workspaces/{account.workspace_id}/documents"
    assert len((await client.get(f"{base}?status=ready", headers=account.headers)).json()) == 1
    assert (await client.get(f"{base}?q=zzz", headers=account.headers)).json() == []
    r = await client.post(f"{base}/{doc['id']}/reindex", headers=account.headers)
    assert r.status_code == 202
    from app.services import jobs

    await jobs.drain()
    assert (await client.get(f"{base}/{doc['id']}", headers=account.headers)).json()[
        "status"
    ] == "ready"
    assert (await client.delete(f"{base}/{doc['id']}", headers=account.headers)).status_code == 204
    assert (await client.get(f"{base}/{doc['id']}", headers=account.headers)).status_code == 404


async def test_workspace_isolation(client: AsyncClient, account: Account) -> None:
    doc = await upload(client, account)
    other = await register(client)
    # Other user can't read the doc via their own workspace path or the owner's.
    r = await client.get(
        f"/api/workspaces/{other.workspace_id}/documents/{doc['id']}", headers=other.headers
    )
    assert r.status_code == 404
    r = await client.get(f"/api/workspaces/{account.workspace_id}/documents", headers=other.headers)
    assert r.status_code == 404
    hits = (
        await client.post(
            f"/api/workspaces/{other.workspace_id}/search",
            json={"query": "remote work VPN"},
            headers=other.headers,
        )
    ).json()
    assert hits == []


async def test_hybrid_search_ranks_relevant_chunk(client: AsyncClient, account: Account) -> None:
    await upload(client, account)
    hits = (
        await client.post(
            f"/api/workspaces/{account.workspace_id}/search",
            json={"query": "Do I need the VPN on public Wi-Fi?", "top_k": 3},
            headers=account.headers,
        )
    ).json()
    assert hits
    assert "VPN" in hits[0]["content"]
    assert hits[0]["score"] >= hits[-1]["score"]
    assert hits[0]["vector_rank"] or hits[0]["keyword_rank"]
