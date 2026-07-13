"""Backfill: (re-)embed all policy PDFs into the active vector backend.

Use this after enabling RAG/pgvector on an existing deployment, or to re-index
after changing the embedding model. Idempotent (upsert by chunk id).

    python -m scripts.embed_policies                 # uses sample_data/policies
    python -m scripts.embed_policies ./my_policies   # a custom directory
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def embed_dir(directory: str) -> None:
    """Load, chunk, embed and upsert every PDF in ``directory``."""
    from core.memory import memory
    from pipelines.ingestion import chunk_text
    from pipelines.intake import extract_text_from_pdf_bytes
    from services import rag

    if not os.path.isdir(directory):
        print(f"no such directory: {directory}")
        return

    pdfs = sorted(f for f in os.listdir(directory) if f.lower().endswith(".pdf"))
    if not pdfs:
        print(f"no PDFs in {directory}")
        return

    total = 0
    for name in pdfs:
        with open(os.path.join(directory, name), "rb") as fh:
            text = extract_text_from_pdf_bytes(fh.read())
        chunks = chunk_text(text)
        doc_id = name.replace(".pdf", "")
        chunk_dicts = [
            {
                "text": c,
                "doc_id": doc_id,
                "metadata": {"source": name, "chunk_index": i},
            }
            for i, c in enumerate(chunks)
        ]
        written = await rag.ingest_chunks(chunk_dicts)
        await memory.upsert_policy(
            doc_id=doc_id,
            filename=name,
            chunks=len(chunks),
            char_count=len(text),
            status="ingested" if written else "vector_store_unavailable",
        )
        total += written
        flag = f"{written} vectors" if written else "registry only (no vector backend)"
        print(f"  ✓ {name:32} {len(chunks)} chunks → {flag}")

    print(f"\nDone. {total} chunks embedded into the active vector backend.")


def main() -> None:
    directory = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.join(os.path.dirname(__file__), "..", "sample_data", "policies")
    )
    asyncio.run(embed_dir(directory))


if __name__ == "__main__":
    main()
