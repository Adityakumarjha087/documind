"""Application settings, loaded from environment variables / .env."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LLMProviderName = Literal["fake", "openai", "anthropic", "gemini", "ollama"]
EmbeddingProviderName = Literal["hash", "openai", "gemini", "ollama"]
RerankerName = Literal["none", "lexical", "cohere"]
DEFAULT_JWT_SECRET = "change-me-in-production-please-32b"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    app_name: str = "DocuMind"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # Database / infra
    database_url: str = "postgresql+asyncpg://documind:documind@localhost:5442/documind"
    redis_url: str = "redis://localhost:6389/0"
    ingestion_mode: Literal["celery", "inline"] = "celery"

    # Object storage (MinIO / S3). backend "local" writes to a directory instead.
    storage_backend: Literal["s3", "local"] = "s3"
    storage_local_dir: str = ".storage"
    s3_endpoint_url: str | None = "http://localhost:9010"
    s3_access_key: str = "documind"
    s3_secret_key: str = "documind-secret"
    s3_bucket: str = "documind"
    s3_region: str = "us-east-1"
    max_upload_mb: int = 25

    # Auth
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14

    # Rate limiting (requests per window per client)
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    rate_limit_auth_requests: int = 10

    # LLM
    llm_provider: LLMProviderName = "fake"
    llm_model: str | None = None  # provider default when unset
    llm_max_tokens: int = 2048
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # Embeddings
    embedding_provider: EmbeddingProviderName = "hash"
    embedding_model: str | None = None
    embedding_dim: int = 768

    # Retrieval
    chunk_strategy: Literal["recursive", "semantic"] = "recursive"
    chunk_size: int = 900
    chunk_overlap: int = 150
    retrieval_candidates: int = 20
    retrieval_top_k: int = 5
    rrf_k: int = 60
    reranker: RerankerName = "lexical"
    cohere_api_key: str | None = None
    # Guardrail: minimum reranker relevance for the best chunk to attempt an answer.
    min_relevance: float = 0.15

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            if v.strip().startswith("["):
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _production_safety(self) -> Settings:
        if self.environment == "production":
            problems = []
            if self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be set to a random value of at least 32 chars")
            if any(o == "*" for o in self.cors_origins):
                problems.append("CORS_ORIGINS must not contain '*'")
            if self.llm_provider == "fake":
                problems.append("LLM_PROVIDER=fake is for development/CI only")
            if problems:
                raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
