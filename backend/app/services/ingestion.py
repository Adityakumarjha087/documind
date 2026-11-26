"""Document ingestion: load → parse → chunk → embed → persist, updating progress as it goes."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.llm.factory import get_embedder
from app.logs import get_logger
from app.models import Chunk, Document, DocumentStatus
from app.rag import parsing
from app.rag.chunking import recursive_chunks, semantic_chunks
from app.storage import get_storage

log = get_logger(__name__)
EMBED_BATCH = 64


async def _set(session: AsyncSession, doc: Document, status: DocumentStatus, progress: int) -> None:
    doc.status = status
    doc.progress = progress
    await session.commit()


async def ingest_document(sm: async_sessionmaker[AsyncSession], document_id: uuid.UUID) -> None:
    s = get_settings()
    async with sm() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            log.warning("ingest_missing_document", document_id=str(document_id))
            return
        try:
            await _set(session, doc, DocumentStatus.parsing, 5)
            if doc.source_type == "url":
                data, ctype = await parsing.fetch_url(doc.source_uri, s.max_upload_mb * 1024 * 1024)
                kind = parsing.source_type_for_content_type(ctype, doc.source_uri)
                doc.mime_type = ctype or None
                doc.size_bytes = len(data)
            else:
                data = await get_storage().get(doc.source_uri)
                kind = doc.source_type
            parsed = parsing.parse_bytes(data, kind)
            if parsed.title and (doc.title == doc.source_uri or doc.source_type == "url"):
                doc.title = parsed.title[:500]
            doc.num_pages = parsed.num_pages
            await _set(session, doc, DocumentStatus.chunking, 25)

            embedder = get_embedder()
            if doc.chunk_strategy == "semantic":
                chunks = await semantic_chunks(parsed.segments, embedder, s.chunk_size)
            else:
                chunks = recursive_chunks(parsed.segments, s.chunk_size, s.chunk_overlap)
            if not chunks:
                raise parsing.ParseError("No text chunks produced from document")
            await _set(session, doc, DocumentStatus.embedding, 40)

            # Re-ingestion is idempotent: replace any previous chunks.
            await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            for start in range(0, len(chunks), EMBED_BATCH):
                batch = chunks[start : start + EMBED_BATCH]
                vectors = await embedder.embed([c.content for c in batch])
                session.add_all(
                    Chunk(
                        document_id=doc.id,
                        workspace_id=doc.workspace_id,
                        ordinal=start + i,
                        content=c.content,
                        page=c.page,
                        section=c.section,
                        token_count=c.token_count,
                        embedding=v,
                    )
                    for i, (c, v) in enumerate(zip(batch, vectors, strict=True))
                )
                done = min(len(chunks), start + EMBED_BATCH)
                doc.progress = 40 + int(55 * done / len(chunks))
                await session.commit()

            doc.num_chunks = len(chunks)
            doc.error = None
            await _set(session, doc, DocumentStatus.ready, 100)
            log.info("ingest_complete", document_id=str(doc.id), chunks=len(chunks))
        except Exception as e:
            await session.rollback()
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = DocumentStatus.failed
                doc.error = getattr(e, "message", None) or str(e) or e.__class__.__name__
                await session.commit()
            log.warning("ingest_failed", document_id=str(document_id), error=str(e))


async def pending_document_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.execute(
        select(Document.id).where(Document.status == DocumentStatus.queued)
    )
    return list(rows.scalars())
