from __future__ import annotations

import uuid

import numpy as np
import pytest

from app.llm.base import ChatMessage, collect
from app.llm.embeddings import HashEmbedder, _fit
from app.llm.fake import FakeLLM, is_elliptical, keywords
from app.llm.pricing import estimate_cost
from app.rag import parsing
from app.rag.chunking import recursive_chunks, semantic_chunks
from app.rag.evaluation import (
    EvalSample,
    context_precision,
    context_recall_heuristic,
    faithfulness_heuristic,
    score_sample,
    summarize,
)
from app.rag.parsing import Segment
from app.rag.pipeline import citation_payload
from app.rag.prompts import build_answer_messages, format_sources
from app.rag.rerank import Candidate, LexicalReranker, NoReranker
from app.rag.retrieval import RetrievedChunk, build_tsquery, reciprocal_rank_fusion


def test_rrf_rewards_agreement() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([[a, b, c], [b, c]], k=60)
    assert fused[b] > fused[a] > 0
    assert fused[b] == pytest.approx(1 / 62 + 1 / 61)


def test_build_tsquery_sanitizes() -> None:
    assert build_tsquery(
        "What's the VPN policy?!; DROP TABLE"
    ) == "drop | policy | s | table | vpn" or "vpn" in (
        build_tsquery("What's the VPN policy?!; DROP TABLE") or ""
    )
    assert build_tsquery("the of and") is None
    q = build_tsquery("x'); delete from users; --") or ""
    assert all(ch.isalnum() or ch in " |" for ch in q)


def test_hash_embedder_is_normalized_and_semantic_ish() -> None:
    e = HashEmbedder(256)
    v1, v2, v3 = (
        np.array(e.embed_one(t))
        for t in ["remote work policy VPN", "VPN policy for remote work", "banana bread recipe"]
    )
    assert np.linalg.norm(v1) == pytest.approx(1.0, abs=1e-5)
    assert float(v1 @ v2) > float(v1 @ v3)
    assert e.embed_one("") == [0.0] * 256
    fitted = _fit([3.0, 4.0, 1.0], 2)
    assert fitted == pytest.approx([0.6, 0.8])


def test_markdown_and_html_parsing() -> None:
    md = parsing.parse_markdown(
        "# Title\nintro text here\n## Part A\nalpha\n```\n# not heading\n```\n"
    )
    assert md.title == "Title"
    assert [s.section for s in md.segments] == ["Title", "Part A"]
    assert "# not heading" in md.segments[1].text
    html = parsing.parse_html(
        "<html><head><title>Doc</title><script>x()</script></head><body><nav>menu</nav>"
        "<main><h2>Intro</h2><p>Hello world paragraph.</p><li>item one</li></main></body></html>"
    )
    assert html.title == "Doc"
    assert html.segments[0].section == "Intro" and "menu" not in html.segments[0].text
    with pytest.raises(parsing.ParseError):
        parsing.parse_html("<html><body></body></html>")
    with pytest.raises(parsing.ParseError):
        parsing.parse_markdown("   ")
    assert parsing.parse_text("Short title\nbody").title == "Short title"
    assert parsing.parse_bytes(b"hello there", "txt").segments[0].text == "hello there"
    with pytest.raises(parsing.ParseError):
        parsing.parse_bytes(b"x", "exe")
    with pytest.raises(parsing.ParseError):
        parsing.parse_pdf(b"%PDF-broken")
    with pytest.raises(parsing.ParseError):
        parsing.parse_docx(b"PKnot-a-zip")


def test_detect_source_type_and_content_types() -> None:
    assert parsing.detect_source_type("A.PDF") == "pdf"
    assert parsing.detect_source_type("notes.markdown") == "md"
    with pytest.raises(parsing.ParseError):
        parsing.detect_source_type("x.pptx")
    assert parsing.source_type_for_content_type("application/pdf", "http://x/y") == "pdf"
    assert parsing.source_type_for_content_type("text/plain", "http://x/y") == "txt"
    assert parsing.source_type_for_content_type("", "http://x/y.md") == "md"
    assert parsing.source_type_for_content_type("text/html", "http://x/") == "html"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "http://localhost/x",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_ssrf_guard(url: str) -> None:
    with pytest.raises(parsing.ParseError):
        parsing.assert_public_url(url)


def test_recursive_chunks_respect_size_and_metadata() -> None:
    text = " ".join(f"Sentence number {i} talks about topic {i % 5}." for i in range(200))
    chunks = recursive_chunks([Segment(text, page=3, section="Body")], size=300, overlap=50)
    assert len(chunks) > 5
    assert all(len(c.content) <= 300 + len("Body\n") for c in chunks)
    assert all(
        c.page == 3 and c.section == "Body" and c.content.startswith("Body\n") for c in chunks
    )


async def test_semantic_chunks_split_on_topic_shift() -> None:
    cats = " ".join(["Cats are small felines that purr and chase mice around the house."] * 4)
    rockets = " ".join(["Rockets burn liquid fuel to escape gravity and reach orbit quickly."] * 4)
    chunks = await semantic_chunks([Segment(f"{cats} {rockets}")], HashEmbedder(256), size=2000)
    assert len(chunks) >= 2
    assert "Cats" in chunks[0].content and "Rockets" in chunks[-1].content
    short = await semantic_chunks([Segment("Only one sentence here.")], HashEmbedder(64), size=100)
    assert len(short) == 1


async def test_rerankers() -> None:
    cands = [
        Candidate("a", "Bananas are yellow fruit.", 0.2),
        Candidate("b", "Remote employees must use the corporate VPN on public Wi-Fi.", 0.3),
    ]
    scores = await LexicalReranker().rerank("corporate VPN on public wifi", cands)
    assert scores[1] > scores[0]
    assert all(0 <= s <= 1 for s in scores)
    assert await NoReranker().rerank("q", [Candidate("x", "t", -0.4)]) == [0.0]


def _chunk(text: str, title: str = "Doc") -> RetrievedChunk:
    return RetrievedChunk(uuid.uuid4(), uuid.uuid4(), title, text, 2, "Sec", 0.9, 0.03)


async def test_fake_llm_extractive_answer_and_rewrite() -> None:
    chunks = [
        _chunk("The stipend is 50 USD per month for remote staff."),
        _chunk("Bananas grow in tropical climates around the world."),
    ]
    msgs = build_answer_messages("How much is the stipend?", chunks, [])
    assert "<sources>" in msgs[-1].content and "page 2, section: Sec" in format_sources(chunks)
    text, res = await collect(FakeLLM(), "system", msgs)
    assert "50 USD" in text and "[1]" in text and "Bananas" not in text
    assert res.usage.completion_tokens > 0
    cites = citation_payload(chunks, text)
    assert cites[0]["cited"] and not cites[1]["cited"]

    rw = await FakeLLM().complete(
        "Rewrite into a standalone question",
        [
            ChatMessage(
                "user",
                "Conversation:\nuser: tell me about the VPN policy\n\n"
                "Follow-up question: what about laptops?",
            )
        ],
    )
    assert "laptops" in rw and "vpn" in rw
    assert "can only answer" in await FakeLLM().complete("sys", [ChatMessage("user", "hi")])
    nothing = await FakeLLM().complete("sys", build_answer_messages("zebra?", chunks[:1], []))
    assert "don't have enough information" in nothing


async def test_eval_metrics() -> None:
    s = EvalSample(
        question="How much is the stipend?",
        answer="The stipend is 50 USD per month for remote staff [1]. Unicorns fly over Mars daily.",
        contexts=[
            "The stipend is 50 USD per month for remote staff.",
            "Unrelated text about fruit.",
        ],
        ground_truth="Remote staff receive a 50 USD monthly stipend.",
    )
    assert faithfulness_heuristic(s) == pytest.approx(0.5)
    assert context_precision(s) == pytest.approx(1.0)
    assert context_recall_heuristic(s) is not None
    swapped = EvalSample(s.question, s.answer, list(reversed(s.contexts)), s.ground_truth)
    assert context_precision(swapped) == pytest.approx(0.5)
    assert context_precision(EvalSample("q", "a", [], None)) is None
    scores = await score_sample(s, HashEmbedder(256))
    assert 0 < scores["answer_relevancy"] <= 1
    judged = await score_sample(s, HashEmbedder(256), FakeLLM())
    assert judged["faithfulness"] == 0.5
    summary = summarize([scores, {**scores, "context_recall": None}])
    assert summary["faithfulness"] == scores["faithfulness"]
    assert keywords("The VPN and the policy") == {"vpn", "policy"}


def test_pricing() -> None:
    assert estimate_cost("claude-opus-5-5", 1_000_000, 0) == 4.0
    assert estimate_cost("unknown", 100, 100) == 0.0


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("and what about security?", True),
        ("Is it free?", True),
        ("Tell me more", True),
        ("Who painted the Mona Lisa?", False),
        ("What is the parental leave policy?", False),
    ],
)
def test_is_elliptical(q: str, expected: bool) -> None:
    assert is_elliptical(q) is expected
