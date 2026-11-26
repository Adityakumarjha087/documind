"""Hybrid retrieval: pgvector cosine + Postgres full-text, fused with Reciprocal Rank Fusion,
then reranked. Every query is scoped to a single workspace (tenant isolation)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.base import EmbeddingProvider
from app.llm.fake import keywords
from app.models import Chunk, Document
from app.rag.rerank import Candidate, Reranker


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    page: int | None
    section: str | None
    score: float  # reranker relevance in [0, 1]
    rrf_score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    timings_ms: dict[str, int] = field(default_factory=dict)

    @property
    def best_score(self) -> float:
        return max((c.score for c in self.chunks), default=0.0)


def reciprocal_rank_fusion(rankings: list[list[uuid.UUID]], k: int = 60) -> dict[uuid.UUID, float]:
    """RRF: score(d) = Σ 1 / (k + rank_i(d)), ranks starting at 1."""
    fused: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return fused


def build_tsquery(query: str) -> str | None:
    """OR-of-keywords tsquery. Keywords are [a-z0-9]+ so the string is injection-safe; it is
    still passed as a bound parameter."""
    terms = sorted(keywords(query))
    return " | ".join(terms) if terms else None


async def vector_search(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    qvec: list[float],
    limit: int,
    document_ids: list[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, float]]:
    distance = Chunk.embedding.cosine_distance(qvec)
    stmt = (
        select(Chunk.id, (1 - distance).label("sim"))
        .where(Chunk.workspace_id == workspace_id)
        .order_by(distance)
        .limit(limit)
    )
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    rows = (await session.execute(stmt)).all()
    return [(r[0], float(r[1])) for r in rows]


async def keyword_search(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    query: str,
    limit: int,
    document_ids: list[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, float]]:
    tsq = build_tsquery(query)
    if not tsq:
        return []
    doc_filter = "AND document_id = ANY(:doc_ids)" if document_ids else ""
    sql = text(
        f"""
        SELECT id, ts_rank_cd(tsv, q, 32) AS rank
        FROM chunks, to_tsquery('english', :tsq) AS q
        WHERE workspace_id = :ws AND tsv @@ q {doc_filter}
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    params: dict[str, object] = {"tsq": tsq, "ws": workspace_id, "limit": limit}
    if document_ids:
        params["doc_ids"] = document_ids
    rows = (await session.execute(sql, params)).all()
    return [(r[0], float(r[1])) for r in rows]


async def hybrid_retrieve(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    query: str,
    embedder: EmbeddingProvider,
    reranker: Reranker,
    top_k: int | None = None,
    candidates: int | None = None,
    document_ids: list[uuid.UUID] | None = None,
) -> RetrievalResult:
    s = get_settings()
    top_k = top_k or s.retrieval_top_k
    n = candidates or s.retrieval_candidates
    timings: dict[str, int] = {}

    t0 = time.perf_counter()
    qvec = (await embedder.embed([query]))[0]
    timings["embed"] = int((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    vec_hits = await vector_search(session, workspace_id, qvec, n, document_ids)
    kw_hits = await keyword_search(session, workspace_id, query, n, document_ids)
    timings["search"] = int((time.perf_counter() - t0) * 1000)

    vec_rank = {cid: i for i, (cid, _) in enumerate(vec_hits, start=1)}
    kw_rank = {cid: i for i, (cid, _) in enumerate(kw_hits, start=1)}
    vec_sim = dict(vec_hits)
    fused = reciprocal_rank_fusion([[c for c, _ in vec_hits], [c for c, _ in kw_hits]], k=s.rrf_k)
    if not fused:
        return RetrievalResult([], timings)

    ordered_ids = sorted(fused, key=lambda c: -fused[c])[:n]
    rows = (
        await session.execute(
            select(Chunk, Document.title)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(ordered_ids), Chunk.workspace_id == workspace_id)
        )
    ).all()
    by_id = {row[0].id: row for row in rows}
    ordered = [by_id[c] for c in ordered_ids if c in by_id]

    # Keyword-only hits have no similarity from the ANN query; compute it in Python.
    missing = [row[0] for row in ordered if row[0].id not in vec_sim]
    for ch in missing:
        vec_sim[ch.id] = float(sum(a * b for a, b in zip(qvec, ch.embedding, strict=False)))

    t0 = time.perf_counter()
    scores = await reranker.rerank(
        query,
        [Candidate(str(row[0].id), row[0].content, vec_sim.get(row[0].id, 0.0)) for row in ordered],
    )
    timings["rerank"] = int((time.perf_counter() - t0) * 1000)

    results = [
        RetrievedChunk(
            chunk_id=ch.id,
            document_id=ch.document_id,
            document_title=title,
            content=ch.content,
            page=ch.page,
            section=ch.section,
            score=score,
            rrf_score=round(fused[ch.id], 6),
            vector_rank=vec_rank.get(ch.id),
            keyword_rank=kw_rank.get(ch.id),
        )
        for (ch, title), score in zip(ordered, scores, strict=True)
    ]
    results.sort(key=lambda r: (-r.score, -r.rrf_score))
    return RetrievalResult(results[:top_k], timings)
