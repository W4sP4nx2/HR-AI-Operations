"""PDF ingestion and chunking for the HR policy RAG pipeline.

Reads PDF policy documents with pypdf, splits the extracted text into
overlapping token-approximate chunks, and returns chunk dicts ready for the
vector store. Chunking uses a simple whitespace tokeniser as a portable
stand-in for a model tokenizer (512 tokens, 50 token overlap by default).
"""

from __future__ import annotations

import os
from typing import Any

from core.config import settings


def extract_text_from_pdf(path: str) -> str:
    """Extract concatenated text from a PDF file.

    Args:
        path: Filesystem path to the PDF.

    Returns:
        The extracted text with page breaks normalised to spaces.
    """
    from pypdf import PdfReader

    from pipelines.intake import _extract_pages

    reader = PdfReader(path)
    return "\n".join(_extract_pages(reader))


def _window(words: list[str], chunk_size: int, overlap: int) -> list[str]:
    """Overlapping fixed-size word windows (used for oversized paragraphs)."""
    out: list[str] = []
    step = max(1, chunk_size - overlap)
    for start in range(0, len(words), step):
        window = words[start : start + chunk_size]
        if not window:
            break
        out.append(" ".join(window))
        if start + chunk_size >= len(words):
            break
    return out


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Split text into **structure-aware** overlapping chunks.

    Respects document structure rather than slicing blindly at a fixed offset:
    the text is split on blank-line paragraph boundaries, paragraphs are packed
    into chunks up to ``chunk_size`` words (carrying ``overlap`` words for
    continuity), and any single paragraph larger than ``chunk_size`` is
    word-windowed. A short single-paragraph doc yields one chunk; a long
    structured handbook yields many semantically-aligned chunks (never one giant
    block that would dilute retrieval or overflow a prompt).

    Args:
        text: The source text.
        chunk_size: Approximate words per chunk (defaults to settings).
        overlap: Word overlap between consecutive chunks (defaults to settings).

    Returns:
        A list of chunk strings.
    """
    import re

    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return _window(text.split(), chunk_size, overlap)

    chunks: list[str] = []
    cur: list[str] = []
    for para in paragraphs:
        pwords = para.split()
        if len(pwords) > chunk_size:
            # Paragraph alone exceeds the budget → flush, then window it.
            if cur:
                chunks.append(" ".join(cur))
                cur = []
            chunks.extend(_window(pwords, chunk_size, overlap))
            continue
        if len(cur) + len(pwords) > chunk_size:
            chunks.append(" ".join(cur))
            cur = cur[-overlap:] if overlap else []  # carry overlap for continuity
        cur.extend(pwords)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def ingest_pdf(path: str, doc_id: str | None = None) -> list[dict[str, Any]]:
    """Read and chunk a single PDF into vector-store-ready records.

    Args:
        path: Path to the PDF file.
        doc_id: Optional document identifier; defaults to the file name.

    Returns:
        A list of chunk dicts with ``text``, ``doc_id`` and ``metadata``.
    """
    doc_id = doc_id or os.path.basename(path)
    text = extract_text_from_pdf(path)
    chunks = chunk_text(text)
    return [
        {
            "text": chunk,
            "doc_id": doc_id,
            "metadata": {"source": path, "chunk_index": idx},
        }
        for idx, chunk in enumerate(chunks)
    ]


def ingest_directory(directory: str) -> list[dict[str, Any]]:
    """Ingest every PDF in a directory.

    Args:
        directory: Path containing policy PDFs.

    Returns:
        A combined list of chunk dicts across all PDFs found.
    """
    records: list[dict[str, Any]] = []
    if not os.path.isdir(directory):
        return records
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(".pdf"):
            records.extend(ingest_pdf(os.path.join(directory, name)))
    return records
