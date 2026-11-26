"""Deterministic offline provider.

It answers *extractively*: it picks the context sentences that best overlap the question and
cites them. This keeps the full pipeline (streaming, citations, guardrails, evaluation) usable and
testable without any API key.
"""

from __future__ import annotations

import asyncio
import math
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
_SOURCE_BLOCK = re.compile(r"\[(\d+)\] ?([^\n]*)\n(.*?)(?=\n\[\d+\]|\n</sources>|\Z)", re.S)


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


def stem(word: str) -> str:
    """Tiny suffix stripper so "plans"/"plan" and "employees"/"employee" match."""
    for suf in ("ies", "ied"):
        if len(word) > len(suf) + 2 and word.endswith(suf):
            return word[: -len(suf)] + "y"  # carried -> carry, policies -> policy
    for suf in ("ing", "es", "ed", "ly", "s"):
        if len(word) > len(suf) + 3 and word.endswith(suf):
            return word[: -len(suf)]
    return word


def stemmed_keywords(text: str) -> set[str]:
    return {stem(w) for w in keywords(text)}


def _is_heading(line: str, prev: str) -> bool:
    """A heading is a short line that starts a block (after a blank line or a finished sentence)
    and either has no terminal punctuation or is a question (FAQ-style headings)."""
    starts_block = not prev or prev.endswith((".", "!", "?", ":"))
    return (
        starts_block
        and len(line) <= 70
        and line[:1].isupper()
        and (line.endswith("?") or not line.endswith((".", "!", ":", ";", ",")))
    )


def _sentences(text: str) -> list[tuple[str, str]]:
    """Return (sentence, heading) pairs. Headings are kept as matching context but never
    returned as answer text; lines wrapped mid-sentence are re-joined into paragraphs."""
    out: list[tuple[str, str]] = []
    heading, prev = "", ""
    para: list[str] = []

    def flush() -> None:
        for part in re.split(r"(?<=[.!?])\s+", " ".join(para)):
            if len(part.strip()) > 20:
                out.append((part.strip(), heading))
        para.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            prev = ""
            continue
        if _is_heading(line, prev):
            flush()
            heading = line
        else:
            para.append(line)
        prev = line
    flush()
    return out


class FakeLLM:
    name = "fake"

    def __init__(self, model: str | None = None, delay: float = 0.0) -> None:
        self.model = model or "fake-extractive-1"
        self.delay = delay

    def _answer(self, system: str, messages: list[ChatMessage]) -> str:
        question = messages[-1].content if messages else ""
        # Query-rewrite task
        if system.lower().startswith("rewrite the follow-up question"):
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
        m = re.search(r"Question:\s*(.*?)(?:\nStandalone question:\s*(.*))?\s*$", qpart, re.S)
        own = m.group(1) if m else qpart
        primary = stemmed_keywords(own) or stemmed_keywords(question)
        secondary = stemmed_keywords(m.group(2) or "") - primary if m else set()
        candidates: list[tuple[int, int, int, str]] = []  # (primary, secondary, source, text)
        headings: dict[str, str] = {}
        title_terms: dict[int, set[str]] = {}
        for num, header, body in _SOURCE_BLOCK.findall(ctx_match.group(1) + "\n</sources>"):
            # Words in the document title describe the whole document, not a specific answer.
            title_terms[int(num)] = stemmed_keywords(re.sub(r"\(.*\)\s*$", "", header))
            for sent, heading in _sentences(body):
                s_terms = stemmed_keywords(f"{heading} {sent}")
                p_hit, s_hit = len(primary & s_terms), len(secondary & s_terms)
                if p_hit or s_hit:
                    candidates.append((p_hit, s_hit, int(num), sent))
                    headings[sent] = heading
        # The user's own words decide relevance; context terms only break ties.
        if any(c[0] for c in candidates):
            candidates = [c for c in candidates if c[0]]
        # Rare terms (e.g. "plans") count for more than words found everywhere (e.g. "Acme").
        n = len(candidates) or 1
        texts = {c[3]: stemmed_keywords(c[3]) for c in candidates}
        df: dict[str, int] = {}
        for terms in texts.values():
            for t in terms:
                df[t] = df.get(t, 0) + 1

        def weight(terms: set[str], title: set[str]) -> float:
            return sum(
                (1.0 + math.log(1 + n / df.get(t, 1))) * (0.3 if t in title else 1.0) for t in terms
            )

        scored: list[tuple[float, int, str]] = []
        for _, _, num, text in candidates:
            s_terms = texts[text] | stemmed_keywords(headings[text])
            title = title_terms.get(num, set())
            score = weight(primary & s_terms, title) + 0.25 * weight(secondary & s_terms, title)
            scored.append((score / (1 + len(texts[text]) ** 0.5), num, text))
        if not scored:
            return "I don't have enough information in the provided documents to answer that."
        scored.sort(key=lambda t: -t[0])
        # Keep only sentences close to the best match, so loosely related lines are dropped.
        cutoff = scored[0][0] * 0.6
        picked, seen = [], set()
        for score, num, sent in scored:
            if score < cutoff:
                break
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
