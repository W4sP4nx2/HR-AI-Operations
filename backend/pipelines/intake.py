"""Input intake: turn raw text, PDF uploads, or URLs into agent-ready text.

This is the front door for *what gets passed to the system*. Agents work on
plain text; this module normalises the three ways a human or an upstream system
provides that text:

  * **text**  — typed/pasted directly,
  * **pdf**   — an uploaded PDF attachment (resume, policy, ticket export),
  * **url**   — a link the system scrapes for its readable content.

Heavy/optional dependencies (pypdf for PDFs, httpx+BeautifulSoup for scraping)
are imported lazily. If a capability is not installed, a
:class:`CapabilityUnavailable` is raised so the API can return a precise
``status="unavailable"`` rather than a generic error.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

# Cap extracted text so a giant PDF/page can't blow up an LLM prompt or the DB.
MAX_CHARS = 20000


class CapabilityUnavailable(RuntimeError):
    """Raised when an intake capability (PDF/scrape) is not installed/reachable."""

    def __init__(self, capability: str, detail: str = "") -> None:
        self.capability = capability
        self.detail = detail
        super().__init__(f"{capability} unavailable" + (f": {detail}" if detail else ""))


def enforce_upload_size(data: bytes | None) -> None:
    """Reject uploads larger than ``MAX_UPLOAD_SIZE_MB`` (DoS + cost guard).

    Raises ``ValueError`` with a clear message so the route returns ``status=
    error`` rather than buffering/parsing an arbitrarily large file.
    """
    if not data:
        return
    from core.config import settings

    limit = settings.max_upload_size_mb * 1024 * 1024
    if len(data) > limit:
        raise ValueError(
            f"file too large ({len(data) // (1024 * 1024)} MB); "
            f"limit is {settings.max_upload_size_mb} MB"
        )


@dataclass
class IntakeResult:
    """Normalised intake output.

    Attributes:
        text: The extracted, length-capped text.
        source_type: One of ``"text"``, ``"pdf"``, ``"url"``.
        source_ref: A human-readable reference (filename, url, or ``"inline"``).
        chars: Length of the extracted text before capping note.
    """

    text: str
    source_type: str
    source_ref: str
    chars: int

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary (without the full text)."""
        return {
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "chars": self.chars,
            "truncated": self.chars > MAX_CHARS,
        }


def _cap(text: str) -> str:
    """Trim text to :data:`MAX_CHARS` and collapse excess whitespace."""
    text = " ".join(text.split())
    return text[:MAX_CHARS]


def _extract_pages(reader) -> list[str]:
    """Extract page text **layout-aware**, falling back to flow mode per page.

    ``extraction_mode="layout"`` preserves physical positioning, so a two-column
    resume ("Skills" left / "Experience" right) isn't scrambled into one
    interleaved line before it reaches the embedder. Layout mode can fail on some
    malformed PDFs, so each page falls back to the default flow extraction.
    """
    pages: list[str] = []
    for page in reader.pages:
        try:
            txt = page.extract_text(extraction_mode="layout") or ""
        except Exception:  # noqa: BLE001 - fall back to flow mode for this page
            txt = page.extract_text() or ""
        pages.append(txt)
    return pages


def extract_text_from_pdf_bytes(data: bytes) -> str:
    """Extract text from in-memory PDF bytes.

    Args:
        data: Raw PDF file content.

    Returns:
        Concatenated page text.

    Raises:
        CapabilityUnavailable: if pypdf is not installed.
        ValueError: if the bytes are not a readable PDF.
    """
    try:
        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001
        raise CapabilityUnavailable("pdf", "pypdf not installed") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = _extract_pages(reader)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"could not read PDF: {exc}") from exc
    return "\n".join(pages)


def extract_text_from_url(url: str, timeout: float = 10.0) -> str:
    """Fetch a URL and extract its readable text (a lightweight scraper).

    Args:
        url: An ``http(s)://`` URL to scrape.
        timeout: Network timeout in seconds.

    Returns:
        Visible page text with script/style stripped.

    Raises:
        CapabilityUnavailable: if httpx/bs4 are missing or the fetch fails.
        ValueError: if the URL scheme is not http(s).
    """
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("only http(s) URLs are supported")
    try:
        import httpx
        from bs4 import BeautifulSoup
    except Exception as exc:  # noqa: BLE001
        raise CapabilityUnavailable("scrape", "httpx/beautifulsoup4 not installed") from exc

    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "HR-Command-Center/1.0 (+intake-scraper)"},
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - network/HTTP problems are "unavailable"
        raise CapabilityUnavailable("scrape", f"fetch failed: {exc}") from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator=" ")


def resolve_input(
    text: str | None = None,
    pdf_bytes: bytes | None = None,
    filename: str | None = None,
    url: str | None = None,
) -> IntakeResult:
    """Resolve exactly one of text/pdf/url into normalised :class:`IntakeResult`.

    Precedence when multiple are provided: ``pdf`` > ``url`` > ``text``.

    Args:
        text: Raw inline text.
        pdf_bytes: Uploaded PDF content.
        filename: Original filename of the upload (for the reference label).
        url: A URL to scrape.

    Returns:
        The normalised intake result.

    Raises:
        ValueError: if no input is provided or extraction yields nothing.
        CapabilityUnavailable: if a required intake capability is missing.
    """
    if pdf_bytes:
        raw = extract_text_from_pdf_bytes(pdf_bytes)
        ref, stype = (filename or "upload.pdf"), "pdf"
    elif url:
        raw = extract_text_from_url(url)
        ref, stype = url, "url"
    elif text and text.strip():
        raw, ref, stype = text, "inline", "text"
    else:
        raise ValueError("no input provided (need text, pdf, or url)")

    capped = _cap(raw)
    if not capped.strip():
        raise ValueError(f"no extractable text from {stype} source")
    return IntakeResult(text=capped, source_type=stype, source_ref=ref, chars=len(raw))
