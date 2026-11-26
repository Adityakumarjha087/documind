"""Anthropic Claude provider (official SDK, streaming)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessageParam

from app.errors import UpstreamError
from app.llm.base import ChatMessage, StreamResult

DEFAULT_MODEL = "claude-opus-5-5"


def to_anthropic_messages(messages: list[ChatMessage]) -> list[BetaMessageParam]:
    out: list[BetaMessageParam] = []
    for m in messages:
        if m.role == "assistant":
            out.append({"role": "assistant", "content": m.content})
        else:
            out.append({"role": "user", "content": m.content})
    return out


class AnthropicLLM:
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None,
        model: str | None = None,
        max_tokens: int = 2048,
        http_client: Any = None,
    ) -> None:
        # api_key=None lets the SDK resolve credentials from env / `ant auth login` profiles.
        kwargs: dict[str, Any] = {"http_client": http_client} if http_client else {}
        if api_key:
            kwargs["api_key"] = api_key
        self.client = anthropic.AsyncAnthropic(**kwargs)
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
            async with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                system=system,
                messages=to_anthropic_messages(messages),
                # RAG answering is latency-sensitive and the grounding work is done by retrieval.
                output_config={"effort": "low"},
                # Server-side fallback on a policy refusal instead of a dead-end response.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except anthropic.APIConnectionError as e:
            raise UpstreamError("Could not reach the Anthropic API") from e
        except anthropic.RateLimitError as e:
            raise UpstreamError("Anthropic rate limit reached, retry shortly") from e
        except anthropic.APIStatusError as e:
            raise UpstreamError(f"Anthropic API error ({e.status_code})") from e
        if final.stop_reason == "refusal":
            yield "\n\nI can't help with that request."
        result.model = final.model
        result.usage.prompt_tokens = final.usage.input_tokens
        result.usage.completion_tokens = final.usage.output_tokens

    async def complete(
        self, system: str, messages: list[ChatMessage], max_tokens: int | None = None
    ) -> str:
        result = StreamResult()
        return "".join([t async for t in self.stream(system, messages, result, max_tokens)])
