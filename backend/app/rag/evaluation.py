"""RAGAS-style evaluation: faithfulness, answer relevancy, context precision, context recall.

Metric definitions follow RAGAS (Es et al., 2023). Two judge backends:
* ``llm``       - the configured LLM scores faithfulness / recall (used when a real provider is set)
* ``heuristic`` - deterministic lexical-attribution approximations (offline / CI)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from app.llm.base import ChatMessage, EmbeddingProvider, LLMProvider
from app.llm.fake import keywords

_SENT = re.compile(r"(?<=[.!?])\s+")
_CITE = re.compile(r"\[\d+\]")


@dataclass
class EvalSample:
    question: str
    answer: str
    contexts: list[str]
    ground_truth: str | None = None


def _claims(text: str) -> list[str]:
    text = _CITE.sub("", text).replace("Based on the documents:", "")
    return [s.strip() for s in _SENT.split(text) if len(keywords(s)) >= 2]


def _supported(claim: str, contexts: list[str], threshold: float = 0.6) -> bool:
    ck = keywords(claim)
    if not ck:
        return True
    return any(len(ck & keywords(ctx)) / len(ck) >= threshold for ctx in contexts)


def faithfulness_heuristic(sample: EvalSample) -> float:
    claims = _claims(sample.answer)
    if not claims:
        return 0.0
    return sum(_supported(c, sample.contexts) for c in claims) / len(claims)


def context_recall_heuristic(sample: EvalSample) -> float | None:
    if not sample.ground_truth:
        return None
    gt_claims = _claims(sample.ground_truth) or [sample.ground_truth]
    return sum(_supported(c, sample.contexts, 0.5) for c in gt_claims) / len(gt_claims)


def context_precision(sample: EvalSample) -> float | None:
    """Mean precision@k over ranks holding a relevant context (RAGAS context_precision)."""
    if not sample.ground_truth or not sample.contexts:
        return None if not sample.ground_truth else 0.0
    gt = keywords(sample.ground_truth)
    if not gt:
        return None
    rel = [len(gt & keywords(c)) / len(gt) >= 0.3 for c in sample.contexts]
    hits, total = 0, 0.0
    for k, r in enumerate(rel, start=1):
        if r:
            hits += 1
            total += hits / k
    return total / hits if hits else 0.0


async def answer_relevancy(sample: EvalSample, embedder: EmbeddingProvider) -> float:
    if not sample.answer.strip():
        return 0.0
    q, a = await embedder.embed([sample.question, _CITE.sub("", sample.answer)])
    sim = float(np.dot(np.array(q), np.array(a)))
    return max(0.0, min(1.0, sim))


JUDGE_SYSTEM = (
    "You are a strict evaluator. Respond with only a number between 0 and 1, nothing else."
)


async def _llm_score(llm: LLMProvider, prompt: str) -> float | None:
    raw = await llm.complete(JUDGE_SYSTEM, [ChatMessage("user", prompt)], max_tokens=10)
    m = re.search(r"\d*\.?\d+", raw)
    if not m:
        return None
    return max(0.0, min(1.0, float(m.group())))


async def score_sample(
    sample: EvalSample, embedder: EmbeddingProvider, llm: LLMProvider | None = None
) -> dict[str, float | None]:
    ctx = "\n---\n".join(sample.contexts)
    faith: float | None
    recall: float | None
    if llm is not None:
        faith = await _llm_score(
            llm,
            f"Context:\n{ctx}\n\nAnswer:\n{sample.answer}\n\nWhat fraction of the claims in the "
            "answer are directly supported by the context?",
        )
        recall = None
        if sample.ground_truth:
            recall = await _llm_score(
                llm,
                f"Context:\n{ctx}\n\nReference answer:\n{sample.ground_truth}\n\nWhat fraction of "
                "the reference answer's statements can be attributed to the context?",
            )
        if faith is None:
            faith = faithfulness_heuristic(sample)
        if recall is None:
            recall = context_recall_heuristic(sample)
    else:
        faith = faithfulness_heuristic(sample)
        recall = context_recall_heuristic(sample)
    return {
        "faithfulness": round(faith, 4),
        "answer_relevancy": round(await answer_relevancy(sample, embedder), 4),
        "context_precision": _round(context_precision(sample)),
        "context_recall": _round(recall),
    }


def summarize(rows: list[dict[str, float | None]]) -> dict[str, float]:
    keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    out: dict[str, float] = {}
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        if vals:
            out[k] = round(sum(v for v in vals if v is not None) / len(vals), 4)
    return out


def _round(v: float | None) -> float | None:
    return None if v is None else round(v, 4)
