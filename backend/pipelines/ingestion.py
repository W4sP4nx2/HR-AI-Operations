"""PDF ingestion and chunking for the HR policy RAG pipeline.

Reads PDF policy documents with pypdf, splits the extracted text into
overlapping token-approximate chunks, and returns chunk dicts ready for the
vector store. Chunking uses a simple whitespace tokeniser as a portable
stand-in for a model tokenizer (500 tokens, 50 token overlap by default).
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

from core.config import settings

_POLICY_HEADER = {
    "effective_date": re.compile(r"\bEffective Date:\s*(\d{4}-\d{2}-\d{2})"),
    # PDF extraction may flatten line boundaries, so stop at the next governed
    # header instead of relying on a newline.
    "expires_on": re.compile(r"\bExpires On:\s*(.*?)\s+Status:", re.DOTALL),
    "status": re.compile(r"\bStatus:\s*([A-Za-z_-]+)"),
}
_VERSIONED_POLICY_ID = re.compile(r"^(policy_[a-z0-9_]+)_(20\d{2})(?:\.pdf)?$", re.IGNORECASE)
_SECTION_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\s+)?([A-Z][A-Za-z0-9 &/()_-]{2,80}?)(?:\.|:)?$")


@dataclass(frozen=True)
class ChunkingPlan:
    """A deterministic, auditable decision for one document ingestion."""

    strategy: str
    goal: str
    reason: str
    token_budget: int
    overlap_tokens: int
    section_count: int

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-safe plan metadata for APIs and vector records."""
        return asdict(self)


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
            # Carry as much overlap as fits. A fixed suffix plus a large next
            # paragraph can otherwise create an over-sized chunk at the
            # paragraph boundary (for example 50 + 480 words in a 500 window).
            carry = min(overlap, max(0, chunk_size - len(pwords)))
            cur = cur[-carry:] if carry else []
        cur.extend(pwords)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _paragraphs(text: str) -> list[str]:
    """Return non-empty source paragraphs with PDF line wrapping normalised."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _section_title(paragraph: str) -> str | None:
    """Extract a short structural heading from a paragraph when present."""
    first_line = paragraph.split("\n", 1)[0].strip()
    inline_heading = re.match(r"^([A-Z][A-Za-z0-9 &/()_-]{2,80})\.\s", first_line)
    if inline_heading and len(inline_heading.group(1).split()) <= 8:
        return inline_heading.group(1).strip()
    match = _SECTION_HEADING.match(first_line)
    if match and len(first_line.split()) <= 12:
        return match.group(1).strip()
    sentence = first_line.split(". ", 1)[0].strip()
    if sentence.endswith("."):
        sentence = sentence[:-1]
    if 2 <= len(sentence.split()) <= 8 and sentence.istitle():
        return sentence
    return None


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """Split a document into ``(section title, paragraphs)`` without loss."""
    sections: list[tuple[str, list[str]]] = []
    current_title = "Document context"
    current: list[str] = []
    for paragraph in _paragraphs(text):
        title = _section_title(paragraph)
        if title and current:
            sections.append((current_title, current))
            current_title, current = title, [paragraph]
        else:
            current.append(paragraph)
    if current:
        sections.append((current_title, current))
    return sections or [("Document context", [text])]


def plan_chunking(text: str, goal: str = "policy_retrieval") -> ChunkingPlan:
    """Choose a chunking strategy from document structure and retrieval goal.

    This is an agentic planning step with deterministic local reasoning: it
    decomposes a document, evaluates its structure, and records why a strategy
    was selected. It deliberately does not call a provider, so PDF ingestion
    remains offline-capable and BYOK keys never escape the request boundary.
    """
    sections = _sections(text)
    words = len(text.split())
    if len(sections) >= 3 or words >= settings.chunk_size * 2:
        strategy = "hierarchical"
        reason = "multiple titled sections or long document; preserve section lineage for precise retrieval"
    elif len(_paragraphs(text)) >= 3:
        strategy = "semantic"
        reason = "multi-paragraph document; keep coherent paragraphs together before applying the token budget"
    else:
        strategy = "fixed"
        reason = "short or unstructured source; use overlapping token windows"
    return ChunkingPlan(
        strategy=strategy,
        goal=goal,
        reason=reason,
        token_budget=settings.chunk_size,
        overlap_tokens=settings.chunk_overlap,
        section_count=len(sections),
    )


def semantic_chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Pack coherent paragraph units before falling back to token windows.

    The semantic strategy never breaks a paragraph when it fits. Oversized
    paragraphs use the same bounded overlap as fixed chunking, preserving a
    reliable fallback when an embedding model is unavailable offline.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for paragraph in _paragraphs(text):
        words = paragraph.split()
        if len(words) > chunk_size:
            if current:
                chunks.append(" ".join(current))
                current, current_words = [], 0
            chunks.extend(_window(words, chunk_size, overlap))
            continue
        if current and current_words + len(words) > chunk_size:
            chunks.append(" ".join(current))
            carry = min(overlap, current_words, max(0, chunk_size - len(words)))
            current = [" ".join(current).split()[-carry:]] if carry else []
            current_words = carry
        current.append(paragraph)
        current_words += len(words)
    if current:
        chunks.append(" ".join(current))
    return chunks or chunk_text(text, chunk_size, overlap)


def chunk_document(
    text: str,
    *,
    doc_id: str = "document",
    source: str = "",
    goal: str = "policy_retrieval",
) -> tuple[ChunkingPlan, list[dict[str, Any]]]:
    """Plan and create vector-store-ready chunks with structural metadata."""
    plan = plan_chunking(text, goal)
    records: list[dict[str, Any]] = []
    if plan.strategy == "hierarchical":
        for section_index, (section_title, paragraphs) in enumerate(_sections(text)):
            section_text = "\n\n".join(paragraphs)
            for chunk_index, chunk in enumerate(
                semantic_chunk_text(section_text, plan.token_budget, plan.overlap_tokens)
            ):
                records.append(
                    {
                        "text": chunk,
                        "doc_id": doc_id,
                        "metadata": {
                            "source": source,
                            "chunk_index": len(records),
                            "chunk_strategy": plan.strategy,
                            "chunk_goal": plan.goal,
                            "document_title": doc_id,
                            "section_title": section_title,
                            "section_index": section_index,
                            "section_chunk_index": chunk_index,
                            "parent_chunk_id": f"{doc_id}:section:{section_index}",
                        },
                    }
                )
    else:
        pieces = (
            semantic_chunk_text(text, plan.token_budget, plan.overlap_tokens)
            if plan.strategy == "semantic"
            else chunk_text(text, plan.token_budget, plan.overlap_tokens)
        )
        for index, chunk in enumerate(pieces):
            records.append(
                {
                    "text": chunk,
                    "doc_id": doc_id,
                    "metadata": {
                        "source": source,
                        "chunk_index": index,
                        "chunk_strategy": plan.strategy,
                        "chunk_goal": plan.goal,
                        "document_title": doc_id,
                        "section_title": "Document context",
                        "section_index": 0,
                        "parent_chunk_id": f"{doc_id}:document",
                    },
                }
            )
    return plan, records


def extract_policy_metadata(text: str, doc_id: str, source: str) -> dict[str, Any]:
    """Extract temporal policy metadata from a governed policy document.

    The synthetic corpus writes a strict human-readable header into every PDF.
    Keeping those fields as structured metadata lets retrieval apply lifecycle
    rules without relying on semantic similarity or filename ordering.
    """
    metadata: dict[str, Any] = {"source": source}
    for field, pattern in _POLICY_HEADER.items():
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            if field == "status":
                value = value.lower()
            elif field == "expires_on" and value.upper() == "ACTIVE":
                value = ""
            metadata[field] = value

    version_match = _VERSIONED_POLICY_ID.match(doc_id)
    if version_match:
        family, year = version_match.groups()
        metadata["policy_family"] = family.lower()
        metadata["policy_version"] = int(year)
    return metadata


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
    plan, records = chunk_document(text, doc_id=doc_id, source=path)
    policy_metadata = extract_policy_metadata(text, doc_id, path)
    for record in records:
        record["metadata"].update(policy_metadata)
        record["metadata"]["chunking_plan"] = plan.as_dict()
    return records


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
