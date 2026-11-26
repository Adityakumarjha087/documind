"""Gemini and Ollama providers over their REST APIs (streaming)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.errors import UpstreamError
from app.llm.base import ChatMessage, StreamResult, estimate_tokens


class GeminiLLM:
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self, api_key: str | None, model: str | None = None, max_tokens: int = 2048
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for the gemini provider")
        self.api_key = api_key
        self.model = model or "gemini-2.0-flash"
        self.max_tokens = max_tokens

    async def stream(
        self,
        system: str,
        messages: list[ChatMessage],
        result: StreamResult,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in messages
            ],
            "generationConfig": {"maxOutputTokens": max_tokens or self.max_tokens},
        }
        url = f"{self.BASE}/models/{self.model}:streamGenerateContent?alt=sse"
        try:
            async with (
                httpx.AsyncClient(timeout=120) as client,
                client.stream(
                    "POST", url, json=body, headers={"x-goog-api-key": self.api_key}
                ) as resp,
            ):
                if resp.status_code >= 400:
                    raise UpstreamError(f"Gemini API error ({resp.status_code})")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:])
                    for cand in data.get("candidates", []):
                        for part in cand.get("content", {}).get("parts", []):
                            if part.get("text"):
                                yield part["text"]
                    if meta := data.get("usageMetadata"):
                        result.usage.prompt_tokens = meta.get("promptTokenCount", 0)
                        result.usage.completion_tokens = meta.get("candidatesTokenCount", 0)
        except httpx.HTTPError as e:
            raise UpstreamError("Could not reach the Gemini API") from e
        result.model = self.model

    async def complete(
        self, system: str, messages: list[ChatMessage], max_tokens: int | None = None
    ) -> str:
        result = StreamResult()
        return "".join([t async for t in self.stream(system, messages, result, max_tokens)])


class OllamaLLM:
    name = "ollama"

    def __init__(self, base_url: str, model: str | None = None, max_tokens: int = 2048) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model or "llama3.1"
        self.max_tokens = max_tokens

    async def stream(
        self,
        system: str,
        messages: list[ChatMessage],
        result: StreamResult,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        body = {
            "model": self.model,
            "stream": True,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
            "options": {"num_predict": max_tokens or self.max_tokens},
        }
        out: list[str] = []
        try:
            async with (
                httpx.AsyncClient(timeout=300) as client,
                client.stream("POST", f"{self.base_url}/api/chat", json=body) as resp,
            ):
                if resp.status_code >= 400:
                    raise UpstreamError(f"Ollama error ({resp.status_code})")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if text := data.get("message", {}).get("content"):
                        out.append(text)
                        yield text
                    if data.get("done"):
                        result.usage.prompt_tokens = data.get("prompt_eval_count", 0)
                        result.usage.completion_tokens = data.get("eval_count", 0)
        except httpx.HTTPError as e:
            raise UpstreamError("Could not reach Ollama") from e
        if not result.usage.completion_tokens:
            result.usage.completion_tokens = estimate_tokens("".join(out))
        result.model = self.model

    async def complete(
        self, system: str, messages: list[ChatMessage], max_tokens: int | None = None
    ) -> str:
        result = StreamResult()
        return "".join([t async for t in self.stream(system, messages, result, max_tokens)])
