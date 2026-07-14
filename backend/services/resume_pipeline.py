"""Format-aware resume parsing with explicit fallbacks.

The parser is deliberately independent from model inference.  It turns a
resume upload into bounded text and metadata, then a caller may choose a
Fireworks structured extractor or a deterministic review path.  Optional
parsers (OCR, DOCX, HTML) fail with a precise capability signal rather than
silently pretending that an empty document was parsed successfully.

Supported inputs:

* text, Markdown, CSV, and LinkedIn-style JSON exports;
* text and scanned PDFs (password-protected PDFs accept a caller-supplied
  password, which is never included in the result or logs);
* PNG/JPEG/WebP images when an OCR engine is installed;
* DOCX files through their zipped Office XML; and
* HTML resumes, including saved LinkedIn pages.

Legacy binary ``.doc`` files use an optional, sandboxed ``antiword``/``catdoc``
converter. If neither converter is installed, the parser returns an explicit
capability-unavailable response rather than widening the attack surface or
pretending that an empty document was parsed.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pipelines.intake import CapabilityUnavailable

MAX_RESUME_BYTES = 25 * 1024 * 1024
MAX_RESUME_PAGES = 50
MAX_RESUME_TEXT_CHARS = 200_000


class ResumeParseError(ValueError):
    """A user-correctable parsing error (for example, a missing PDF password)."""


@dataclass(frozen=True)
class ParsedResume:
    """Bounded parser output safe to pass to a downstream extraction stage."""

    text: str
    source_type: str
    source_ref: str
    confidence: float
    warnings: tuple[str, ...] = ()
    pages: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def needs_human_review(self) -> bool:
        return self.confidence < 0.75 or bool(self.warnings)

    @property
    def needs_vision_fallback(self) -> bool:
        return "vision_fallback_required" in self.warnings

    def as_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        """Return a non-secret summary; raw resume text is opt-in."""
        result: dict[str, Any] = {
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "chars": len(self.text),
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "pages": self.pages,
            "needs_human_review": self.needs_human_review,
            "needs_vision_fallback": self.needs_vision_fallback,
            "metadata": dict(self.metadata),
        }
        if include_text:
            result["text"] = self.text
        return result


class _VisibleTextParser(HTMLParser):
    """Small stdlib HTML fallback used when BeautifulSoup is unavailable."""

    _ignored = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._ignored:
            self._depth += 1
        if tag.lower() in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._ignored and self._depth:
            self._depth -= 1
        if tag.lower() in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._depth:
            self.parts.append(data)


class ResumeParserPipeline:
    """Parse common resume formats without performing model or network calls."""

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
    TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".log"}
    HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}

    def __init__(
        self,
        *,
        max_bytes: int = MAX_RESUME_BYTES,
        max_chars: int = MAX_RESUME_TEXT_CHARS,
        max_pages: int = MAX_RESUME_PAGES,
    ) -> None:
        if max_bytes < 1 or max_chars < 1 or max_pages < 1:
            raise ValueError("parser limits must be positive")
        self.max_bytes = max_bytes
        self.max_chars = max_chars
        self.max_pages = max_pages

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        *,
        password: str | None = None,
    ) -> ParsedResume:
        """Parse one upload and return bounded text plus quality metadata."""
        if not file_bytes:
            raise ResumeParseError("uploaded resume is empty")
        if len(file_bytes) > self.max_bytes:
            raise ResumeParseError(
                f"resume exceeds the {self.max_bytes // (1024 * 1024)} MB upload limit"
            )
        name = Path(filename or "upload").name
        extension = Path(name).suffix.lower()
        kind = self.detect_type(file_bytes, name)

        if kind == "pdf":
            return self._parse_pdf(file_bytes, name, password=password)
        if kind == "docx":
            return self._finalize(self._extract_docx(file_bytes), "docx", name, confidence=0.90)
        if kind == "html":
            return self._finalize(self._extract_html(file_bytes), "html", name, confidence=0.82)
        if kind == "json":
            return self._finalize(
                self._extract_json(file_bytes), "linkedin_json", name, confidence=0.78
            )
        if kind == "image":
            return self._parse_image(file_bytes, name)
        if kind == "doc":
            return self._finalize(
                self._extract_legacy_doc(file_bytes), "doc", name, confidence=0.78
            )
        if kind == "text" or extension in self.TEXT_EXTENSIONS:
            return self._finalize(
                file_bytes.decode("utf-8", errors="replace"), "text", name, confidence=0.85
            )
        raise ResumeParseError(
            f"unsupported resume format '{extension or 'unknown'}'; use PDF, DOCX, HTML, JSON, image, or text"
        )

    @classmethod
    def detect_type(cls, file_bytes: bytes, filename: str) -> str:
        """Detect by magic bytes first, then by a conservative extension map."""
        extension = Path(filename or "").suffix.lower()
        if file_bytes.startswith(b"%PDF") or extension == ".pdf":
            return "pdf"
        if file_bytes.startswith(b"PK\x03\x04") and extension == ".docx":
            return "docx"
        if (
            file_bytes.startswith((b"<!DOCTYPE", b"<html", b"<HTML"))
            or extension in cls.HTML_EXTENSIONS
        ):
            return "html"
        if extension == ".json":
            return "json"
        if extension == ".doc":
            return "doc"
        if extension in cls.IMAGE_EXTENSIONS or file_bytes.startswith(
            (b"\x89PNG", b"\xff\xd8\xff", b"RIFF")
        ):
            return "image"
        if extension in cls.TEXT_EXTENSIONS or _looks_like_text(file_bytes):
            return "text"
        return "unknown"

    def _parse_pdf(self, data: bytes, name: str, *, password: str | None) -> ParsedResume:
        try:
            from pypdf import PdfReader
        except Exception as exc:  # pragma: no cover - dependency contract
            raise CapabilityUnavailable("pdf_parser", "pypdf is not installed") from exc
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                if not password:
                    raise ResumeParseError("password required for this PDF")
                if reader.decrypt(password) == 0:
                    raise ResumeParseError("PDF password was rejected")
            if len(reader.pages) > self.max_pages:
                raise ResumeParseError(f"resume exceeds the {self.max_pages}-page processing limit")
            pages: list[str] = []
            for page in reader.pages:
                try:
                    page_text = page.extract_text(extraction_mode="layout") or ""
                except Exception:  # noqa: BLE001 - malformed layout metadata
                    page_text = page.extract_text() or ""
                pages.append(page_text)
        except ResumeParseError:
            raise
        except Exception as exc:  # noqa: BLE001 - parser-specific exceptions vary
            raise ResumeParseError(f"could not read PDF: {exc}") from exc

        text = "\n".join(pages)
        if text.strip():
            return self._finalize(text, "pdf_text", name, confidence=0.95, pages=len(pages))

        ocr_text, ocr_warning = self._ocr_pdf(
            data, max_pages=min(max(len(pages), 1), self.max_pages)
        )
        if ocr_text.strip():
            return self._finalize(
                ocr_text,
                "pdf_scanned",
                name,
                confidence=0.72,
                pages=len(pages),
                warnings=(ocr_warning,) if ocr_warning else (),
            )
        warnings = ["vision_fallback_required"]
        if ocr_warning:
            warnings.append(ocr_warning)
        return ParsedResume(
            text="",
            source_type="pdf_scanned",
            source_ref=name,
            confidence=0.0,
            warnings=tuple(warnings),
            pages=len(pages),
            metadata={"bytes": len(data)},
        )

    def _parse_image(self, data: bytes, name: str) -> ParsedResume:
        text, warning = self._ocr_image(data)
        if not text.strip():
            warnings = ["vision_fallback_required"]
            if warning:
                warnings.append(warning)
            return ParsedResume(
                text="",
                source_type="image",
                source_ref=name,
                confidence=0.0,
                warnings=tuple(warnings),
                metadata={"bytes": len(data)},
            )
        return self._finalize(
            text, "image", name, confidence=0.70, warnings=(warning,) if warning else ()
        )

    def _ocr_pdf(self, data: bytes, *, max_pages: int) -> tuple[str, str | None]:
        try:
            import pypdfium2 as pdfium
            import pytesseract
        except ImportError:
            return "", "ocr_unavailable"
        try:
            document = pdfium.PdfDocument(data)
            parts: list[str] = []
            for index in range(min(len(document), max_pages)):
                page = document[index]
                bitmap = page.render(scale=2.0)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    parts.append(pytesseract.image_to_string(image))
                finally:
                    bitmap.close()
                    page.close()
            document.close()
            return "\n".join(parts), None
        except Exception:  # noqa: BLE001 - OCR engines have platform-specific errors
            return "", "ocr_failed"

    def _ocr_image(self, data: bytes) -> tuple[str, str | None]:
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return "", "ocr_unavailable"
        try:
            return pytesseract.image_to_string(Image.open(io.BytesIO(data))), None
        except Exception:  # noqa: BLE001
            return "", "ocr_failed"

    @staticmethod
    def _extract_docx(data: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ResumeParseError(f"could not read DOCX: {exc}") from exc
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise ResumeParseError("DOCX document XML is malformed") from exc
        parts: list[str] = []
        for element in root.iter():
            if element.tag.endswith("}t") and element.text:
                parts.append(element.text)
            elif element.tag.endswith("}p"):
                parts.append("\n")
        return " ".join(parts)

    @staticmethod
    def _extract_legacy_doc(data: bytes) -> str:
        """Use an explicitly installed converter in a short-lived temp file.

        Legacy Word files are OLE binaries and are not safely parsed by the
        standard library.  ``antiword`` and ``catdoc`` are common, narrowly
        scoped converters; they receive only the temporary upload and run with
        ``shell=False`` and a hard timeout.  No converter means an honest
        capability response, not a silent empty resume.
        """
        converter = shutil.which("antiword") or shutil.which("catdoc")
        if not converter:
            raise CapabilityUnavailable(
                "doc_parser",
                "install antiword or catdoc in the quarantined parser worker",
            )
        try:
            with tempfile.NamedTemporaryFile(suffix=".doc") as temporary:
                temporary.write(data)
                temporary.flush()
                completed = subprocess.run(
                    [converter, temporary.name],
                    capture_output=True,
                    timeout=10,
                    check=False,
                    shell=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise CapabilityUnavailable("doc_parser", "legacy .doc conversion timed out") from exc
        except OSError as exc:
            raise CapabilityUnavailable(
                "doc_parser", "legacy .doc converter could not start"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()[:240]
            raise ResumeParseError(
                f"legacy .doc conversion failed{': ' + detail if detail else ''}"
            )
        return completed.stdout.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_html(data: bytes) -> str:
        decoded = data.decode("utf-8", errors="replace")
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(decoded, "html.parser")
            for tag in soup(["script", "style", "noscript", "svg"]):
                tag.decompose()
            return soup.get_text(separator="\n")
        except ImportError:
            parser = _VisibleTextParser()
            parser.feed(decoded)
            return "".join(parser.parts)

    @staticmethod
    def _extract_json(data: bytes) -> str:
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResumeParseError("LinkedIn JSON export is not valid UTF-8 JSON") from exc
        strings: list[str] = []

        def visit(node: Any, key: str = "") -> None:
            if isinstance(node, str):
                if key.lower() not in {"profilepicture", "image", "avatar", "photo"}:
                    strings.append(node)
            elif isinstance(node, dict):
                for child_key, child in node.items():
                    visit(child, str(child_key))
            elif isinstance(node, list):
                for child in node:
                    visit(child, key)

        visit(value)
        return "\n".join(item for item in strings if item.strip())

    def _finalize(
        self,
        text: str,
        source_type: str,
        source_ref: str,
        *,
        confidence: float,
        pages: int | None = None,
        warnings: tuple[str, ...] = (),
    ) -> ParsedResume:
        normalized = _normalize_text(text, self.max_chars)
        final_warnings = list(warnings)
        if not normalized:
            final_warnings.append("no_extractable_text")
        if len(normalized) >= self.max_chars:
            final_warnings.append("text_truncated")
        return ParsedResume(
            text=normalized,
            source_type=source_type,
            source_ref=source_ref,
            confidence=max(0.0, min(1.0, confidence if normalized else 0.0)),
            warnings=tuple(dict.fromkeys(final_warnings)),
            pages=pages,
            metadata={"words": len(normalized.split())},
        )


def _looks_like_text(data: bytes) -> bool:
    sample = data[:4096]
    if not sample:
        return False
    if b"\x00" in sample:
        return False
    printable = sum(byte in b"\t\n\r" or 32 <= byte < 127 for byte in sample)
    return printable / len(sample) >= 0.90


def _normalize_text(text: str, max_chars: int) -> str:
    text = text.replace("\x00", " ").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    compact: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                compact.append("")
            blank = True
        else:
            compact.append(line)
            blank = False
    return "\n".join(compact).strip()[:max_chars]


def chunk_resume_text(
    text: str, *, chunk_chars: int = 6_000, overlap_chars: int = 300
) -> list[str]:
    """Split normalized resume text without dropping the tail.

    The screening model has a bounded context window. Chunking is therefore a
    worker concern, not a parser truncation side effect. The final chunk always
    remains in the result, and overlap is clamped so it cannot stall progress.
    """
    if chunk_chars < 1 or overlap_chars < 0 or overlap_chars >= chunk_chars:
        raise ValueError("overlap must be non-negative and smaller than chunk size")
    normalized = text.strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    step = chunk_chars - overlap_chars
    while start < len(normalized):
        end = min(start + chunk_chars, len(normalized))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start += step
    return chunks
