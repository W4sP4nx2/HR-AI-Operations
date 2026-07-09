"""HR policy document management endpoints.

HR administrators upload policy PDFs here; the backend extracts text, chunks it,
and ingests it into Qdrant so the Policy Q&A agent and Triage auto-resolution
have current, cited knowledge.

Every ingestion is recorded in the ``policies`` table so the Policies panel can
list what's loaded, how many chunks, and when it was last updated.

Endpoints
---------
POST /policies/ingest   Upload a PDF (multipart) → ingest → registry record.
GET  /policies          List all ingested documents.
DELETE /policies/{id}   Remove from registry (Qdrant cleanup is advisory).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile

from api.responses import fail, ok, unavailable
from core.memory import memory
from core.security import require_role
from pipelines.ingestion import chunk_text
from pipelines.intake import (
    CapabilityUnavailable,
    enforce_upload_size,
    extract_text_from_pdf_bytes,
)

router = APIRouter(prefix="/policies", tags=["policies"])

# Sanitise filenames to safe doc_id fragments.
_UNSAFE = re.compile(r"[^a-zA-Z0-9._-]")


def _doc_id_from_filename(filename: str) -> str:
    """Build a stable doc_id from the upload filename + a short uuid suffix."""
    stem = _UNSAFE.sub("_", filename.rsplit(".", 1)[0])[:60]
    return f"{stem}_{uuid.uuid4().hex[:8]}"


@router.post("/ingest")
async def ingest_policy(
    file: UploadFile = File(...),
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Upload a PDF policy document and ingest it into the vector store.

    The document is extracted, chunked, and written to Qdrant (if available).
    The ingestion record is saved to the policies registry regardless of Qdrant
    availability so HR can see what has been uploaded.

    Returns the ingestion summary: doc_id, filename, chunks written, char count.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return fail("only PDF files are accepted")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        return fail("uploaded file is empty")
    try:
        enforce_upload_size(pdf_bytes)
    except ValueError as exc:
        return fail(str(exc))

    # 1) Extract text. PDF parsing + chunking are CPU-bound and synchronous;
    #    run them in a worker thread so a large upload can't block the event
    #    loop — which would stall concurrent chats trying to write their audit
    #    rows (the single source of truth must always be writable).
    try:
        text = await asyncio.to_thread(extract_text_from_pdf_bytes, pdf_bytes)
    except CapabilityUnavailable as exc:
        return unavailable(str(exc), {"capability": exc.capability})
    except ValueError as exc:
        return fail(str(exc))

    if not text.strip():
        return fail("no extractable text found in this PDF (it may be scanned/image-only)")

    # 2) Chunk (also off the event loop)
    chunks = await asyncio.to_thread(chunk_text, text)
    char_count = len(text)
    doc_id = _doc_id_from_filename(file.filename)

    # 3) Embed + upsert into the active vector backend (pgvector on Postgres,
    #    else Qdrant) — advisory; degrades gracefully.
    written = 0
    vector_error: str | None = None
    try:
        from services import rag

        chunk_dicts = [
            {
                "text": c,
                "doc_id": doc_id,
                "metadata": {"source": file.filename, "chunk_index": i},
            }
            for i, c in enumerate(chunks)
        ]
        written = await rag.ingest_chunks(chunk_dicts)
    except Exception as exc:  # noqa: BLE001
        vector_error = str(exc)

    vector_ok = written > 0

    # 4) Always record in the registry (retain source_text for restore/undo)
    record = await memory.upsert_policy(
        doc_id=doc_id,
        filename=file.filename,
        chunks=len(chunks),
        char_count=char_count,
        status="ingested" if vector_ok else "vector_store_unavailable",
        source_text=text,
    )
    record.pop("source_text", None)  # don't ship the full text back

    return ok(
        {
            **record,
            "vector_ingested": vector_ok,
            "vector_chunks": written,
            "vector_error": vector_error,
            "preview": text[:300].strip(),
        }
    )


@router.get("")
async def list_policies() -> dict[str, Any]:
    """Return active policy documents (soft-deleted ones hidden)."""
    rows = await memory.list_policies()
    for r in rows:
        r.pop("source_text", None)
    return ok(rows)


@router.delete("/{doc_id}")
async def delete_policy(
    doc_id: str,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Soft-delete a policy: hide it + purge its vectors, but keep it restorable.

    The registry row (with the retained source text) is preserved so **Restore**
    can re-embed it — this is the undo path. A scheduled purge can hard-delete
    soft-deleted rows after a retention window.
    """
    policy = await memory.get_policy(doc_id)
    if not policy:
        return fail(f"policy '{doc_id}' not found")
    from services import rag

    removed = await rag.delete_policy(doc_id)  # purge vectors → excluded from RAG
    await memory.set_policy_status(doc_id, "deleted")
    return ok(
        {
            "doc_id": doc_id,
            "deleted": True,
            "chunks_purged": removed,
            "restorable": True,
        }
    )


@router.post("/{doc_id}/restore")
async def restore_policy(
    doc_id: str,
    _: dict[str, Any] = Depends(require_role("manager")),
) -> dict[str, Any]:
    """Restore a soft-deleted policy: re-embed from the retained source text (undo)."""
    policy = await memory.get_policy(doc_id)
    if not policy:
        return fail(f"policy '{doc_id}' not found")

    from services import rag

    text = policy.get("source_text") or ""
    chunks = chunk_text(text) if text else []
    written = 0
    if chunks:
        written = await rag.ingest_chunks(
            [
                {"text": c, "doc_id": doc_id, "metadata": {"chunk_index": i}}
                for i, c in enumerate(chunks)
            ]
        )
    await memory.set_policy_status(doc_id, "ingested" if written else "vector_store_unavailable")
    return ok({"doc_id": doc_id, "restored": True, "vector_chunks": written})
