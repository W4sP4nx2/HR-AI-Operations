"""Prepare Fireworks Batch JSONL from resume PDFs without network access.

The script is intentionally standalone: Python standard library plus pypdf.
It can also pass through existing JSON/JSONL prompt records for compatibility
with older local demos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "accounts/fireworks/models/llama-v3p1-8b-instruct"
DEFAULT_SYSTEM_PROMPT = (
    "You are an HR resume screening assistant. Return concise JSON evidence for "
    "human recruiter review. Do not make autonomous hiring decisions."
)
MAX_BATCH_BYTES = 1024 * 1024 * 1024


class BatchPreparationError(RuntimeError):
    """Raised when an input file cannot be converted into a batch row."""


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise SystemExit("input must be a JSON array or JSONL objects")
    return records


def _custom_id(index: int, path: Path) -> str:
    digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:12]
    return f"resume-{index:05d}-{digest}"


def _redact_contact_fields(text: str) -> str:
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]", text)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", text)
    text = re.sub(
        r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)",
        "[REDACTED_PHONE]",
        text,
    )
    return text


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on local environment
        raise SystemExit("pypdf is required: pip install pypdf") from exc

    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:  # noqa: BLE001 - corrupted pages vary by backend
                raise BatchPreparationError(
                    f"{path.name}: failed to extract page {page_number}: {exc}"
                ) from exc
    except BatchPreparationError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises several parser exceptions
        raise BatchPreparationError(f"{path.name}: failed to read PDF: {exc}") from exc

    text = "\n".join(part.strip() for part in pages if part.strip()).strip()
    if not text:
        raise BatchPreparationError(f"{path.name}: no extractable text")
    return _redact_contact_fields(text)


def _resume_prompt(resume_text: str, job_description: str = "") -> str:
    parts = [
        "Screen this resume for human recruiter review.",
        "Return JSON with score, recommendation, matched_skills, missing_skills, and reasoning.",
        "The output is advisory and must not approve or reject a candidate automatically.",
    ]
    if job_description.strip():
        parts.append(f"\nJob description:\n{job_description.strip()}")
    parts.append(f"\nResume text:\n{resume_text.strip()}")
    return "\n".join(parts)


def _text_records_from_directory(
    directory: Path,
    job_description: str = "",
    *,
    require_job_description: bool = True,
) -> list[dict[str, str]]:
    if require_job_description and not job_description.strip():
        raise SystemExit("--job-description or --job-description-file is required for PDF folders")
    records: list[dict[str, str]] = []
    errors: list[str] = []
    for index, path in enumerate(sorted(directory.glob("*.pdf")), start=1):
        try:
            resume_text = _extract_pdf_text(path)
        except BatchPreparationError as exc:
            errors.append(str(exc))
            continue
        records.append(
            {
                "custom_id": _custom_id(index, path),
                "prompt": _resume_prompt(resume_text, job_description),
            }
        )
    if not records and errors:
        raise SystemExit(
            "no PDFs could be converted:\n" + "\n".join(f"- {item}" for item in errors)
        )
    if not records:
        raise SystemExit("PDF directory contains no .pdf files")
    if errors:
        print(
            "skipped corrupted/unreadable PDFs:\n" + "\n".join(f"- {item}" for item in errors),
            file=sys.stderr,
        )
    return records


def _batch_body(
    *,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def _build_batch_jsonl(
    records: list[dict[str, Any]],
    *,
    model: str,
    system_prompt: str,
    max_tokens: int,
) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for index, record in enumerate(records, start=1):
        custom_id = str(record.get("custom_id") or f"record-{index:05d}")
        prompt = str(record.get("prompt") or record.get("input") or "").strip()
        if not prompt:
            raise ValueError(f"{custom_id}: missing prompt")
        if custom_id in seen:
            raise ValueError(f"duplicate custom_id: {custom_id}")
        seen.add(custom_id)
        lines.append(
            json.dumps(
                {
                    "custom_id": custom_id,
                    "body": _batch_body(
                        model=model,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        max_tokens=max_tokens,
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return "\n".join(lines) + "\n"


def _read_job_description(args: argparse.Namespace) -> str:
    if args.job_description_file:
        return args.job_description_file.read_text(encoding="utf-8")
    return args.job_description or ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a folder of PDF resumes into Fireworks Batch JSONL."
    )
    parser.add_argument("input", type=Path, help="Directory of PDF resumes, JSON, or JSONL")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=Path("output.jsonl"),
        help="Output JSONL path (default: output.jsonl)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--job-description", default="")
    parser.add_argument("--job-description-file", type=Path)
    args = parser.parse_args(argv)

    if not args.input.exists():
        raise SystemExit(f"input not found: {args.input}")
    if args.input.is_dir():
        records = _text_records_from_directory(
            args.input,
            _read_job_description(args),
            require_job_description=False,
        )
    else:
        records = _load_json_records(args.input)

    payload = _build_batch_jsonl(
        records,
        model=args.model,
        system_prompt=args.system_prompt,
        max_tokens=args.max_tokens,
    )
    if len(payload.encode("utf-8")) >= MAX_BATCH_BYTES:
        raise SystemExit("output exceeds the Fireworks 1GB Batch input limit")
    args.output.write_text(payload, encoding="utf-8")
    print(f"wrote {len(records)} unique records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
