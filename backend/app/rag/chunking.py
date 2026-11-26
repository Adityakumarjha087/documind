"""Chunking strategies that preserve page/section metadata.

* recursive - LangChain's RecursiveCharacterTextSplitter (paragraph → sentence → word fallbacks).
* semantic  - split into sentences, embed them, and cut where adjacent-sentence similarity drops
              below a percentile threshold (topic shift), bounded by the chunk size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.llm.base import EmbeddingProvider, estimate_tokens
from app.rag.parsing import Segment


@dataclass
class ChunkData:
    content: str
    page: int | None
    section: str | None
    token_count: int


def recursive_chunks(segments: list[Segment], size: int, overlap: int) -> list[ChunkData]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
        keep_separator="end",
    )
    out: list[ChunkData] = []
    for seg in segments:
        for piece in splitter.split_text(seg.text):
            piece = piece.strip()
            if len(piece) < 20 and out:
                continue
            out.append(_make(piece, seg))
    return out


def _make(text: str, seg: Segment) -> ChunkData:
    """Prefix the section heading ("contextual chunk header") so both the embedding and the
    full-text index see what the passage is about, even when the body never names it."""
    if seg.section and not text.startswith(seg.section):
        text = f"{seg.section}\n{text}"
    return ChunkData(text, seg.page, seg.section, estimate_tokens(text))


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


async def semantic_chunks(
    segments: list[Segment], embedder: EmbeddingProvider, size: int, percentile: float = 25.0
) -> list[ChunkData]:
    out: list[ChunkData] = []
    for seg in segments:
        sents = [s.strip() for s in _SENT.split(seg.text) if s.strip()]
        if len(sents) <= 2:
            if seg.text.strip():
                out.extend(recursive_chunks([seg], size, 0))
            continue
        # Embed each sentence with a little neighbour context to smooth noise.
        windows = [" ".join(sents[max(0, i - 1) : i + 2]) for i in range(len(sents))]
        vecs = np.array(await embedder.embed(windows), dtype=np.float32)
        sims = np.sum(vecs[:-1] * vecs[1:], axis=1)
        threshold = float(np.percentile(sims, percentile))
        buf: list[str] = [sents[0]]
        for i in range(1, len(sents)):
            candidate_len = sum(len(s) + 1 for s in buf) + len(sents[i])
            if sims[i - 1] < threshold or candidate_len > size:
                out.append(_make(" ".join(buf), seg))
                buf = []
            buf.append(sents[i])
        if buf:
            out.append(_make(" ".join(buf), seg))
    # Very long single sentences can exceed size: re-split them recursively.
    final: list[ChunkData] = []
    for c in out:
        if len(c.content) > size * 1.5:
            final.extend(recursive_chunks([Segment(c.content, c.page, c.section)], size, 0))
        else:
            final.append(c)
    return final
