"""Embedding providers. ``hash`` is an offline feature-hashing embedder (no network, no model
download) so ingestion and hybrid search work in CI and demos; swap to a real model via env."""

from __future__ import annotations

import hashlib
import itertools
import math
import re

import httpx
import numpy as np
import openai

from app.errors import UpstreamError

_TOKEN = re.compile(r"[a-z0-9]+")


def _normalize(vec: np.ndarray) -> list[float]:
    norm = float(np.linalg.norm(vec))
    return (vec / norm).tolist() if norm else vec.tolist()


class HashEmbedder:
    """Signed feature hashing over unigrams + bigrams with sublinear TF."""

    name = "hash"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _bucket(self, feat: str) -> tuple[int, float]:
        h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % self.dim
        sign = 1.0 if h[4] & 1 else -1.0
        return idx, sign

    def embed_one(self, text: str) -> list[float]:
        toks = _TOKEN.findall(text.lower())
        counts: dict[str, int] = {}
        for t in toks:
            counts[t] = counts.get(t, 0) + 1
        for a, b in itertools.pairwise(toks):
            counts[f"{a}_{b}"] = counts.get(f"{a}_{b}", 0) + 1
        vec = np.zeros(self.dim, dtype=np.float32)
        for feat, c in counts.items():
            idx, sign = self._bucket(feat)
            vec[idx] += sign * (1 + math.log(c)) * (0.5 if "_" in feat else 1.0)
        return _normalize(vec)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class OpenAIEmbedder:
    name = "openai"

    def __init__(self, api_key: str | None, model: str | None, dim: int) -> None:
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model or "text-embedding-3-small"
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        try:
            for i in range(0, len(texts), 96):
                resp = await self.client.embeddings.create(
                    model=self.model, input=texts[i : i + 96], dimensions=self.dim
                )
                out.extend(d.embedding for d in resp.data)
        except openai.APIError as e:
            raise UpstreamError("OpenAI embeddings failed") from e
        return out


class OllamaEmbedder:
    name = "ollama"

    def __init__(self, base_url: str, model: str | None, dim: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model or "nomic-embed-text"
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}
                )
                resp.raise_for_status()
        except httpx.HTTPError as e:
            raise UpstreamError("Ollama embeddings failed") from e
        vecs = resp.json()["embeddings"]
        return [_fit(v, self.dim) for v in vecs]


class GeminiEmbedder:
    name = "gemini"

    def __init__(self, api_key: str | None, model: str | None, dim: int) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for gemini embeddings")
        self.api_key = api_key
        self.model = model or "text-embedding-004"
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
        reqs = [
            {
                "model": f"models/{self.model}",
                "content": {"parts": [{"text": t}]},
                "outputDimensionality": self.dim,
            }
            for t in texts
        ]
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    url, json={"requests": reqs}, headers={"x-goog-api-key": self.api_key}
                )
                resp.raise_for_status()
        except httpx.HTTPError as e:
            raise UpstreamError("Gemini embeddings failed") from e
        return [_fit(e["values"], self.dim) for e in resp.json()["embeddings"]]


def _fit(vec: list[float], dim: int) -> list[float]:
    """Truncate/pad to the DB column dimension, then renormalize."""
    arr = np.zeros(dim, dtype=np.float32)
    n = min(dim, len(vec))
    arr[:n] = vec[:n]
    return _normalize(arr)
