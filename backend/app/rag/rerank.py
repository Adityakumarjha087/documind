"""Rerankers. Scores are in [0, 1] so the guardrail threshold is comparable across backends."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import get_settings
from app.llm.fake import keywords
from app.llm.fake import stem as _stem
from app.logs import get_logger

log = get_logger(__name__)


@dataclass
class Candidate:
    chunk_id: str
    text: str
    vector_score: float  # cosine similarity in [-1, 1]


class Reranker(Protocol):
    name: str

    async def rerank(self, query: str, candidates: list[Candidate]) -> list[float]: ...


class NoReranker:
    name = "none"

    async def rerank(self, query: str, candidates: list[Candidate]) -> list[float]:
        return [max(0.0, c.vector_score) for c in candidates]


class LexicalReranker:
    """Local cross-scorer: query-term coverage + phrase (bigram) matches + dense similarity.

    It is a dependency-free stand-in for a cross-encoder (BGE / Cohere) that still exploits
    query/passage interaction rather than independent embeddings.
    """

    name = "lexical"

    async def rerank(self, query: str, candidates: list[Candidate]) -> list[float]:
        q_terms = {_stem(w) for w in keywords(query)}
        q_tokens = [_stem(w) for w in re.findall(r"[a-z0-9]+", query.lower())]
        q_bigrams = {f"{a} {b}" for a, b in itertools.pairwise(q_tokens)}
        scores = []
        for c in candidates:
            c_terms = {_stem(w) for w in keywords(c.text)}
            c_tokens = [_stem(w) for w in re.findall(r"[a-z0-9]+", c.text.lower())]
            c_bigrams = {f"{a} {b}" for a, b in itertools.pairwise(c_tokens)}
            coverage = len(q_terms & c_terms) / len(q_terms) if q_terms else 0.0
            phrase = len(q_bigrams & c_bigrams) / len(q_bigrams) if q_bigrams else 0.0
            dense = max(0.0, c.vector_score)
            scores.append(round(0.6 * coverage + 0.15 * phrase + 0.25 * dense, 4))
        return scores


class CohereReranker:
    name = "cohere"

    def __init__(self, api_key: str, fallback: Reranker) -> None:
        self.api_key = api_key
        self.fallback = fallback

    async def rerank(self, query: str, candidates: list[Candidate]) -> list[float]:
        if not candidates:
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.cohere.com/v2/rerank",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": "rerank-v3.5",
                        "query": query,
                        "documents": [c.text for c in candidates],
                    },
                )
                resp.raise_for_status()
        except httpx.HTTPError:
            log.warning("cohere_rerank_failed_using_fallback")
            return await self.fallback.rerank(query, candidates)
        scores = [0.0] * len(candidates)
        for r in resp.json()["results"]:
            scores[r["index"]] = float(r["relevance_score"])
        return scores


def get_reranker() -> Reranker:
    s = get_settings()
    if s.reranker == "cohere" and s.cohere_api_key:
        return CohereReranker(s.cohere_api_key, LexicalReranker())
    if s.reranker == "none":
        return NoReranker()
    return LexicalReranker()
