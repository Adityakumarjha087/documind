"""Pydantic request/response models (API contract)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.models import DocumentStatus, Role


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    workspace_name: str | None = Field(default=None, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    created_at: datetime


# Workspaces
class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    role: Role
    created_at: datetime


class MemberIn(BaseModel):
    email: EmailStr
    role: Role = Role.member


class MemberUpdate(BaseModel):
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role


# Documents
class UrlIngestIn(BaseModel):
    url: HttpUrl
    chunk_strategy: Literal["recursive", "semantic"] = "recursive"


class DocumentOut(ORM):
    id: uuid.UUID
    title: str
    source_type: str
    source_uri: str
    size_bytes: int
    status: DocumentStatus
    progress: int
    error: str | None
    chunk_strategy: str
    num_pages: int | None
    num_chunks: int
    created_at: datetime


class ChunkOut(ORM):
    id: uuid.UUID
    document_id: uuid.UUID
    ordinal: int
    content: str
    page: int | None
    section: str | None


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    page: int | None
    section: str | None
    score: float
    rrf_score: float
    vector_rank: int | None
    keyword_rank: int | None


# Chat
class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(ORM):
    id: uuid.UUID
    title: str
    created_at: datetime


class MessageOut(ORM):
    id: uuid.UUID
    role: str
    content: str
    rewritten_query: str | None
    citations: list[dict[str, Any]]
    grounded: bool
    created_at: datetime
    feedback: int | None = None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class AskIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    document_ids: list[uuid.UUID] | None = None


class FeedbackIn(BaseModel):
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2000)


# Eval
class EvalQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    ground_truth: str | None = Field(default=None, max_length=4000)


class EvalRunIn(BaseModel):
    name: str = Field(default="Evaluation run", max_length=200)
    questions: list[EvalQuestion] = Field(min_length=1, max_length=100)
    judge: Literal["heuristic", "llm"] = "heuristic"


class EvalRunOut(ORM):
    id: uuid.UUID
    name: str
    status: str
    summary: dict[str, float]
    results: list[dict[str, Any]]
    config: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None


# Analytics
class DailyPoint(BaseModel):
    day: str
    queries: int
    avg_latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class AnalyticsOut(BaseModel):
    days: int
    total_queries: int
    avg_latency_ms: float
    p95_latency_ms: float
    total_tokens: int
    total_cost_usd: float
    grounded_rate: float
    feedback_up: int
    feedback_down: int
    documents: int
    chunks: int
    daily: list[DailyPoint]
