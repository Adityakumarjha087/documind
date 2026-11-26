"""Document upload / URL ingestion, listing, chunk preview, deletion, and raw hybrid search."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import MemberCtx, SessionDep
from app.errors import Forbidden, NotFound, PayloadTooLarge
from app.llm.factory import get_embedder
from app.logs import get_logger
from app.models import ROLE_RANK, Chunk, Document, DocumentStatus, Role
from app.rag.parsing import ParseError, assert_public_url, detect_source_type
from app.rag.rerank import get_reranker
from app.rag.retrieval import hybrid_retrieve
from app.schemas import ChunkOut, DocumentOut, SearchHit, SearchIn, UrlIngestIn
from app.services.jobs import enqueue_ingestion
from app.storage import get_storage

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["documents"])
log = get_logger(__name__)


async def _dispatch(session: SessionDep, doc: Document) -> None:
    """Queue ingestion; if the broker is unreachable, record a visible, retryable failure."""
    try:
        enqueue_ingestion(doc.id)
    except Exception as e:
        log.error("enqueue_failed", document_id=str(doc.id), error=str(e))
        doc.status = DocumentStatus.failed
        doc.error = "Could not queue ingestion (job queue unavailable). Use re-index to retry."
        await session.commit()


MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
}


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    ctx: MemberCtx,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    chunk_strategy: Annotated[Literal["recursive", "semantic"], Form()] = "recursive",
) -> Document:
    s = get_settings()
    filename = file.filename or "upload"
    kind = detect_source_type(filename)
    limit = s.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLarge(f"File exceeds {s.max_upload_mb} MB")
    if not data:
        raise ParseError("File is empty")
    if kind == "pdf" and not data.startswith(b"%PDF"):
        raise ParseError("File is not a valid PDF")
    if kind == "docx" and not data.startswith(b"PK"):
        raise ParseError("File is not a valid DOCX")

    doc_id = uuid.uuid4()
    key = f"{ctx.workspace.id}/{doc_id}/{filename.replace('/', '_')[-200:]}"
    await get_storage().put(key, data, MIME[kind])
    doc = Document(
        id=doc_id,
        workspace_id=ctx.workspace.id,
        uploaded_by=ctx.user.id,
        title=filename.rsplit(".", 1)[0][:500],
        source_type=kind,
        source_uri=key,
        mime_type=MIME[kind],
        size_bytes=len(data),
        chunk_strategy=chunk_strategy,
        meta={"filename": filename},
    )
    session.add(doc)
    await session.commit()
    await _dispatch(session, doc)
    return doc


@router.post("/documents/url", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def ingest_url(body: UrlIngestIn, ctx: MemberCtx, session: SessionDep) -> Document:
    url = str(body.url)
    assert_public_url(url)
    doc = Document(
        workspace_id=ctx.workspace.id,
        uploaded_by=ctx.user.id,
        title=url[:500],
        source_type="url",
        source_uri=url,
        chunk_strategy=body.chunk_strategy,
        meta={"url": url},
    )
    session.add(doc)
    await session.commit()
    await _dispatch(session, doc)
    return doc


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    ctx: MemberCtx,
    session: SessionDep,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[Document]:
    stmt = select(Document).where(Document.workspace_id == ctx.workspace.id)
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{q}%"))
    return list((await session.execute(stmt.order_by(Document.created_at.desc()))).scalars())


async def _get_doc(session: SessionDep, ctx: MemberCtx, document_id: uuid.UUID) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None or doc.workspace_id != ctx.workspace.id:
        raise NotFound("Document not found")
    return doc


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> Document:
    return await _get_doc(session, ctx, document_id)


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    document_id: uuid.UUID,
    ctx: MemberCtx,
    session: SessionDep,
    page: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[Chunk]:
    await _get_doc(session, ctx, document_id)
    stmt = select(Chunk).where(Chunk.document_id == document_id)
    if page is not None:
        stmt = stmt.where(Chunk.page == page)
    return list((await session.execute(stmt.order_by(Chunk.ordinal).limit(limit))).scalars())


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
async def get_chunk(chunk_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> Chunk:
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.workspace_id != ctx.workspace.id:
        raise NotFound("Chunk not found")
    return chunk


@router.post("/documents/{document_id}/reindex", response_model=DocumentOut, status_code=202)
async def reindex_document(document_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> Document:
    doc = await _get_doc(session, ctx, document_id)
    doc.status, doc.progress, doc.error = DocumentStatus.queued, 0, None
    await session.commit()
    await _dispatch(session, doc)
    return doc


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> None:
    doc = await _get_doc(session, ctx, document_id)
    if doc.uploaded_by != ctx.user.id and ROLE_RANK[ctx.role] < ROLE_RANK[Role.admin]:
        raise Forbidden("Only the uploader or an admin can delete this document")
    if doc.source_type != "url":
        await get_storage().delete(doc.source_uri)
    await session.delete(doc)
    await session.commit()


@router.post("/search", response_model=list[SearchHit])
async def search(body: SearchIn, ctx: MemberCtx, session: SessionDep) -> list[SearchHit]:
    result = await hybrid_retrieve(
        session, ctx.workspace.id, body.query, get_embedder(), get_reranker(), top_k=body.top_k
    )
    return [SearchHit(**c.__dict__) for c in result.chunks]
