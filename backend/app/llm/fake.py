"""Deterministic offline provider.

It answers *extractively*: it picks the context sentences that best overlap the question and
cites them. This keeps the full pipeline (streaming, citations, guardrails, evaluation) usable and
testable without any API key.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from app.llm.base import ChatMessage, StreamResult, estimate_tokens

_WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "why",
        "when",
        "where",
        "does",
        "do",
        "did",
        "can",
        "could",
        "should",
        "would",
        "will",
        "with",
        "by",
        "from",
        "as",
        "at",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "about",
        "into",
        "than",
        "then",
        "there",
        "their",
        "they",
        "them",
        "i",
        "you",
        "we",
        "our",
        "your",
        "me",
        "my",
        "tell",
        "explain",
        "please",
        "get",
        "gets",
        "got",
        "give",
        "gives",
        "make",
        "need",
        "needs",
        "want",
        "any",
        "some",
        "much",
        "there",
        "here",
        "also",
        "just",
    ]
)
_SOURCE_BLOCK = re.compile(r"\[(\d+)\][^\n]*\n(.*?)(?=\n\[\d+\]|\n</sources>|\Z)", re.S)


def keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1}


_ELLIPTICAL = re.compile(
    r"^(and|also|what about|how about|what else|why|how so|is it|does it|can it|it|that|this|"
    r"they|those|these|more|tell me more)\b",
    re.I,
)
_PRONOUN = re.compile(r"\b(it|its|that|this|they|them|those|these|he|she|there)\b", re.I)


def is_elliptical(question: str) -> bool:
    """Heuristic for follow-ups that depend on prior turns ("and what about X?", "is it free?")."""
    q = question.strip()
    return bool(_ELLIPTICAL.match(q)) or (len(keywords(q)) <= 2 and bool(_PRONOUN.search(q)))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20]


class FakeLLM:
    name = "fake"

    def __init__(self, model: str | None = None, delay: float = 0.0) -> None:
        self.model = model or "fake-extractive-1"
        self.delay = delay

    def _answer(self, system: str, messages: list[ChatMessage]) -> str:
        question = messages[-1].content if messages else ""
        # Query-rewrite task
        if "standalone question" in system.lower():
            m = re.search(r"Follow-up question:\s*(.+)", question, re.S)
            follow = (m.group(1) if m else question).strip()
            if not is_elliptical(follow):
                return follow  # self-contained question / topic switch: don't inherit context
            hist = re.findall(r"user:\s*(.+)", question)
            prior = hist[-1] if hist else ""
            extra = " ".join(sorted(keywords(prior) - keywords(follow)))
            return f"{follow} {extra}".strip()
        # Judge task: return a score
        if "respond with only a number" in system.lower():
            return "0.5"
        ctx_match = re.search(r"<sources>(.*)</sources>", question, re.S)
        if not ctx_match:
            return "I can only answer questions about the documents in this workspace."
        qpart = question[ctx_match.end() :]
        q_terms = keywords(qpart) or keywords(question)
        scored: list[tuple[float, int, str]] = []
        for num, body in _SOURCE_BLOCK.findall(ctx_match.group(1) + "\n</sources>"):
            for sent in _sentences(body):
                overlap = len(q_terms & keywords(sent))
                if overlap:
                    scored.append((overlap / (1 + len(keywords(sent)) ** 0.5), int(num), sent))
        if not scored:
            return "I don't have enough information in the provided documents to answer that."
        scored.sort(key=lambda t: -t[0])
        picked, seen = [], set()
        for _, num, sent in scored:
            if sent in seen:
                continue
            seen.add(sent)
            picked.append(f"{sent} [{num}]")
            if len(picked) == 3:
                break
        return "Based on the documents: " + " ".join(picked)

    async def stream(
        self,
        system: str,
        messages: list[ChatMessage],
        result: StreamResult,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        text = self._answer(system, messages)
        for tok in re.findall(r"\S+\s*", text):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield tok
        result.model = self.model
        result.usage.prompt_tokens = estimate_tokens(system + "".join(m.content for m in messages))
        result.usage.completion_tokens = estimate_tokens(text)

    async def complete(
        self, system: str, messages: list[ChatMessage], max_tokens: int | None = None
    ) -> str:
        return self._answer(system, messages)
