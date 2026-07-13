"""Explicitly gated scanned-resume extraction through Fireworks Vision."""

from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.config import settings
from pipelines.intake import CapabilityUnavailable


class ResumeExperience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None
    title: str | None
    start_date: str | None
    end_date: str | None
    summary: str | None


class ResumeExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    email: str | None
    phone: str | None
    skills: list[str]
    experience: list[ResumeExperience]
    education: list[str]
    warnings: list[str] = Field(default_factory=list)


def render_pdf_pages(pdf_bytes: bytes, *, max_pages: int) -> list[str]:
    """Render bounded PDF pages as PNG data URLs without writing them to disk."""
    if not pdf_bytes:
        raise ValueError("resume PDF is empty")
    if max_pages < 1 or max_pages > 30:
        raise ValueError("RESUME_VLM_MAX_PAGES must be between 1 and 30")
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise CapabilityUnavailable("resume_vision", "pypdfium2 is not installed") from exc

    try:
        document = pdfium.PdfDocument(pdf_bytes)
        if len(document) < 1:
            raise ValueError("resume PDF has no pages")
        urls: list[str] = []
        for page_number in range(min(len(document), max_pages)):
            page = document[page_number]
            bitmap = page.render(scale=110 / 72)
            try:
                image = bitmap.to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                urls.append(f"data:image/png;base64,{encoded}")
            finally:
                bitmap.close()
                page.close()
        return urls
    except CapabilityUnavailable:
        raise
    except Exception as exc:
        raise ValueError(f"could not render resume PDF: {exc}") from exc
    finally:
        if "document" in locals():
            document.close()


def extraction_to_screening_text(extraction: ResumeExtraction) -> str:
    """Convert validated fields to scoring text while excluding contact details."""
    lines = [f"Name: {extraction.name or 'unknown'}"]
    if extraction.skills:
        lines.append("Skills: " + ", ".join(extraction.skills))
    for item in extraction.experience:
        lines.append(
            "Experience: "
            + " | ".join(
                value
                for value in (
                    item.title,
                    item.company,
                    item.start_date,
                    item.end_date,
                    item.summary,
                )
                if value
            )
        )
    if extraction.education:
        lines.append("Education: " + ", ".join(extraction.education))
    return "\n".join(lines)


async def parse_resume_pdf(
    pdf_bytes: bytes,
    *,
    session_id: str | None = None,
) -> tuple[ResumeExtraction, dict[str, Any]]:
    """Render, call the allowlisted VLM, and validate the strict resume schema."""
    from core.fireworks import (
        build_resume_vision_body,
        configured_models,
        validate_model,
    )
    from core.llm_factory import pick_model_for_role, run_fireworks_chat_body
    from core.runtime_key import llm_active, llm_provider

    if not settings.enable_resume_vlm:
        raise CapabilityUnavailable(
            "resume_vision",
            "disabled; set ENABLE_RESUME_VLM=true only after approving image egress",
        )
    if llm_provider() != "fireworks" or not llm_active():
        raise CapabilityUnavailable(
            "resume_vision",
            "a configured Fireworks key, base URL and allowlisted model are required",
        )

    configured = configured_models()
    model_id = settings.fireworks_vision_model.strip()
    if model_id:
        validate_model(model_id)
    else:
        model_id = pick_model_for_role("resume_vision", configured)

    image_urls = await asyncio.to_thread(
        render_pdf_pages,
        pdf_bytes,
        max_pages=settings.resume_vlm_max_pages,
    )
    body = build_resume_vision_body(
        model_id=model_id,
        image_urls=image_urls,
        session_id=session_id,
    )
    raw = await run_fireworks_chat_body(body, session_id=session_id)
    try:
        extraction = ResumeExtraction.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Fireworks resume extraction failed schema validation") from exc
    return extraction, {
        "mode": "fireworks_vlm",
        "pages": len(image_urls),
        "warnings": len(extraction.warnings),
    }
