"""OpenAI provider (official SDK, streaming chat completions)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import openai
from openai.types.chat import ChatCompletionMessageParam

from app.errors import UpstreamError
from app.llm.base import ChatMessage, StreamResult

DEFAULT_MODEL = "gpt-4o-mini"


def to_openai_messages(
    system: str, messages: list[ChatMessage]
) -> list[ChatCompletionMessageParam]:
    out: list[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
    for m in messages:
        if m.role == "assistant":
            out.append({"role": "assistant", "content": m.content})
        else:
            out.append({"role": "user", "content": m.content})
    return out


class OpenAILLM:
    name = "openai"

    def __init__(
        self,
        api_key: str | None,
        model: str | None = None,
        max_tokens: int = 2048,
        base_url: str | None = None,
        http_client: Any = None,
    ) -> None:
        self.client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, http_client=http_client
        )
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens

    async def stream(
        self,
        system: str,
        messages: list[ChatMessage],
        result: StreamResult,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                messages=to_openai_messages(system, messages),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if chunk.usage:
                    result.usage.prompt_tokens = chunk.usage.prompt_tokens
                    result.usage.completion_tokens = chunk.usage.completion_tokens
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.APIError as e:
            raise UpstreamError(f"OpenAI API error: {e.__class__.__name__}") from e
        result.model = self.model

    async def complete(
        self, system: str, messages: list[ChatMessage], max_tokens: int | None = None
    ) -> str:
        result = StreamResult()
        return "".join([t async for t in self.stream(system, messages, result, max_tokens)])
