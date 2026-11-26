"""Provider-agnostic LLM interface. Every provider streams text and reports token usage."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class StreamResult:
    """Mutable holder populated once the stream completes."""

    usage: Usage = field(default_factory=Usage)
    model: str = ""


class LLMProvider(Protocol):
    name: str
    model: str

    def stream(
        self,
        system: str,
        messages: list[ChatMessage],
        result: StreamResult,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield text deltas; fill ``result.usage`` when finished."""
        ...

    async def complete(
        self, system: str, messages: list[ChatMessage], max_tokens: int | None = None
    ) -> str: ...


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) for providers that don't report usage."""
    return max(1, len(text) // 4)


async def collect(
    provider: LLMProvider, system: str, messages: list[ChatMessage], max_tokens: int | None = None
) -> tuple[str, StreamResult]:
    result = StreamResult()
    parts = [delta async for delta in provider.stream(system, messages, result, max_tokens)]
    return "".join(parts), result
