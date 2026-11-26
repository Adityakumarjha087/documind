"""Select LLM / embedding providers from settings (``LLM_PROVIDER``, ``EMBEDDING_PROVIDER``)."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.llm.base import EmbeddingProvider, LLMProvider


@lru_cache
def get_llm() -> LLMProvider:
    s = get_settings()
    match s.llm_provider:
        case "anthropic":
            from app.llm.anthropic_provider import AnthropicLLM

            return AnthropicLLM(s.anthropic_api_key, s.llm_model, s.llm_max_tokens)
        case "openai":
            from app.llm.openai_provider import OpenAILLM

            return OpenAILLM(s.openai_api_key, s.llm_model, s.llm_max_tokens)
        case "gemini":
            from app.llm.http_providers import GeminiLLM

            return GeminiLLM(s.gemini_api_key, s.llm_model, s.llm_max_tokens)
        case "ollama":
            from app.llm.http_providers import OllamaLLM

            return OllamaLLM(s.ollama_base_url, s.llm_model, s.llm_max_tokens)
        case _:
            from app.llm.fake import FakeLLM

            return FakeLLM(s.llm_model)


@lru_cache
def get_embedder() -> EmbeddingProvider:
    s = get_settings()
    from app.llm import embeddings as e

    match s.embedding_provider:
        case "openai":
            return e.OpenAIEmbedder(s.openai_api_key, s.embedding_model, s.embedding_dim)
        case "ollama":
            return e.OllamaEmbedder(s.ollama_base_url, s.embedding_model, s.embedding_dim)
        case "gemini":
            return e.GeminiEmbedder(s.gemini_api_key, s.embedding_model, s.embedding_dim)
        case _:
            return e.HashEmbedder(s.embedding_dim)
