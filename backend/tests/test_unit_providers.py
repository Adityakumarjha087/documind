"""Provider adapters tested against mocked HTTP (no network, no keys)."""

from __future__ import annotations

import json

import httpx
import httpx2
import pytest
import respx

from app.errors import UpstreamError
from app.llm.anthropic_provider import AnthropicLLM
from app.llm.base import ChatMessage, StreamResult, collect
from app.llm.embeddings import GeminiEmbedder, OllamaEmbedder, OpenAIEmbedder
from app.llm.http_providers import GeminiLLM, OllamaLLM
from app.llm.openai_provider import OpenAILLM

MSGS = [ChatMessage("user", "hi"), ChatMessage("assistant", "hello"), ChatMessage("user", "q?")]


def _sse(events: list[tuple[str | None, dict]]) -> bytes:
    out = []
    for name, data in events:
        if name:
            out.append(f"event: {name}")
        out.append(f"data: {json.dumps(data)}\n")
    return ("\n".join(out) + "\n").encode()


async def test_anthropic_stream() -> None:
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        seen["beta"] = request.headers.get("anthropic-beta")
        msg = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 0},
        }
        body = _sse(
            [
                ("message_start", {"type": "message_start", "message": msg}),
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "Hello "},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "world [1]"},
                    },
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                (
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                        "usage": {"output_tokens": 5},
                    },
                ),
                ("message_stop", {"type": "message_stop"}),
            ]
        )
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})

    llm = AnthropicLLM(
        "sk-test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    text, res = await collect(llm, "be grounded", MSGS)
    assert text == "Hello world [1]"
    assert res.usage.prompt_tokens == 12 and res.usage.completion_tokens == 5
    assert seen["model"] == "claude-opus-5-5" and seen["system"] == "be grounded"
    assert [m["role"] for m in seen["messages"]] == ["user", "assistant", "user"]
    assert "server-side-fallback" in seen["beta"]


async def test_anthropic_error_maps_to_upstream() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}},
        )

    llm = AnthropicLLM(
        "sk-test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    with pytest.raises(UpstreamError):
        await llm.complete("s", MSGS)


async def test_openai_stream() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body["messages"][0] == {"role": "system", "content": "sys"}
        chunks = [
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "gpt-4o-mini",
                "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}],
            },
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "gpt-4o-mini",
                "choices": [],
                "usage": {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8},
            },
        ]
        text = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx2.Response(
            200, content=text.encode(), headers={"content-type": "text/event-stream"}
        )

    llm = OpenAILLM(
        "sk-test",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        base_url="http://mock/v1",
    )
    text, res = await collect(llm, "sys", MSGS)
    assert text == "Hi" and res.usage.prompt_tokens == 7


async def test_openai_embeddings_and_errors() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if body["input"] == ["boom"]:
            return httpx2.Response(500, json={"error": {"message": "x"}})
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "m",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.1] * 4}
                    for i in range(len(body["input"]))
                ],
            },
        )

    emb = OpenAIEmbedder("sk", None, 4)
    emb.client = OpenAILLM(
        "sk",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        base_url="http://mock/v1",
    ).client.with_options(max_retries=0)
    assert len(await emb.embed(["a", "b"])) == 2
    with pytest.raises(UpstreamError):
        await emb.embed(["boom"])


@respx.mock
async def test_gemini_stream_and_embed() -> None:
    data = {
        "candidates": [{"content": {"parts": [{"text": "Gem"}]}}],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
    }
    respx.post(url__regex=r".*streamGenerateContent.*").mock(
        return_value=httpx.Response(200, text=f"data: {json.dumps(data)}\n\n")
    )
    respx.post(url__regex=r".*batchEmbedContents").mock(
        return_value=httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0, 0.0]}]})
    )
    text, res = await collect(GeminiLLM("key"), "s", MSGS)
    assert text == "Gem" and res.usage.prompt_tokens == 3
    vec = (await GeminiEmbedder("key", None, 2).embed(["x"]))[0]
    assert vec == pytest.approx([1.0, 0.0])
    with pytest.raises(ValueError):
        GeminiLLM(None)


@respx.mock
async def test_ollama_stream_embed_and_failure() -> None:
    lines = [
        {"message": {"content": "Lla"}, "done": False},
        {"message": {"content": "ma"}, "done": True, "prompt_eval_count": 4, "eval_count": 2},
    ]
    respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))
    )
    respx.post("http://ollama:11434/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[0.0, 2.0, 5.0]]})
    )
    text, res = await collect(OllamaLLM("http://ollama:11434"), "s", MSGS)
    assert text == "Llama" and res.usage.completion_tokens == 2
    assert (await OllamaEmbedder("http://ollama:11434", None, 2).embed(["x"]))[0] == pytest.approx(
        [0, 1]
    )
    respx.post("http://down:1/api/chat").mock(side_effect=httpx.ConnectError("nope"))
    with pytest.raises(UpstreamError):
        await OllamaLLM("http://down:1").complete("s", MSGS)


async def test_stream_result_defaults() -> None:
    assert StreamResult().usage.prompt_tokens == 0
