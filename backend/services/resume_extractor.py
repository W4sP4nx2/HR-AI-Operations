"""Schema-constrained resume extraction through the configured Fireworks path."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.config import settings
from services.resume_pipeline import ParsedResume
from services.skill_normalizer import NormalizedSkill, SkillOntologyMapper


class ExtractedExperience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = None
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    skills_used: list[str] = Field(default_factory=list)


class ExtractedEducation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    start_year: int | None = None
    end_year: int | None = None


class ExtractedResume(BaseModel):
    """Strict, reviewable extraction contract for resume data."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    work_experience: list[ExtractedExperience] = Field(default_factory=list)
    education: list[ExtractedEducation] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    total_years_experience: float = Field(default=0.0, ge=0.0, le=80.0)
    has_gaps: bool = False
    gap_explanation: str | None = None
    warnings: list[str] = Field(default_factory=list)


EXTRACTED_RESUME_SCHEMA: dict[str, Any] = ExtractedResume.model_json_schema()


def build_extraction_body(
    *,
    model_id: str,
    resume_text: str,
    max_tokens: int = 800,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Build a bounded Fireworks/OpenAI-compatible JSON-schema request."""
    from core.fireworks import validate_model

    validate_model(model_id)
    text = resume_text.strip()
    if not text:
        raise ValueError("resume text must not be empty")
    if len(text) > settings.max_llm_input_tokens * 4:
        text = text[: settings.max_llm_input_tokens * 4]
    if not 1 <= max_tokens <= settings.max_llm_output_tokens:
        raise ValueError(f"max_tokens must be between 1 and {settings.max_llm_output_tokens}")
    user_content: str | list[dict[str, Any]] = (
        "Return valid JSON matching the ExtractedResume schema.\n\n" f"Resume text:\n{text}"
    )
    if image_urls:
        user_content = [
            {
                "type": "text",
                "text": (
                    "Return valid JSON matching the ExtractedResume schema. "
                    "Extract only visible resume facts; record uncertainty in warnings."
                ),
            },
            *[{"type": "image_url", "image_url": {"url": image_url}} for image_url in image_urls],
        ]
    return {
        "model": model_id,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract resume facts for human review. Do not infer protected traits, "
                    "do not invent missing facts, normalize dates to YYYY-MM where possible, "
                    "and record ambiguity in warnings. This output is advisory and must not "
                    "make an autonomous hiring decision."
                ),
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ExtractedResume",
                "strict": True,
                "schema": EXTRACTED_RESUME_SCHEMA,
            },
        },
    }


def resolve_resume_model(model_id: str | None = None) -> str:
    """Resolve an operator-injected resume model without baking in a model ID."""
    requested = (
        model_id or os.environ.get("FIREWORKS_RESUME_MODEL", "") or settings.fireworks_vision_model
    ).strip()
    if requested:
        from core.fireworks import validate_model

        return validate_model(requested)
    from core.fireworks import configured_models
    from core.llm_factory import pick_model_for_role

    return pick_model_for_role("resume_extraction", configured_models())


async def extract_resume(
    parsed: ParsedResume,
    *,
    model_id: str | None = None,
    session_id: str | None = None,
) -> tuple[ExtractedResume, dict[str, Any]]:
    """Extract a parsed resume with Fireworks structured output and certify it."""
    from core.llm_factory import run_fireworks_chat_body
    from core.runtime_key import llm_active, llm_provider

    if not parsed.text.strip():
        raise ValueError("resume parser produced no text; use the vision route")
    if llm_provider() != "fireworks" or not llm_active():
        raise RuntimeError("Fireworks resume extraction requires an active configured provider")
    body = build_extraction_body(
        model_id=resolve_resume_model(model_id),
        resume_text=parsed.text,
    )
    raw = await run_fireworks_chat_body(body, session_id=session_id)
    try:
        extraction = ExtractedResume.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Fireworks resume response failed ExtractedResume validation") from exc
    return extraction, {
        "mode": "fireworks_structured",
        "model": body["model"],
        "parser": parsed.as_dict(),
    }


async def extract_resume_images(
    image_bytes: list[bytes],
    *,
    model_id: str | None = None,
    session_id: str | None = None,
) -> tuple[ExtractedResume, dict[str, Any]]:
    """Run the same strict contract over bounded image pages."""
    from core.llm_factory import run_fireworks_chat_body
    from core.runtime_key import llm_active, llm_provider

    if not image_bytes:
        raise ValueError("at least one resume image is required")
    if len(image_bytes) > 30:
        raise ValueError("at most 30 resume images may be sent in one request")
    urls: list[str] = []
    total_bytes = 0
    for data in image_bytes:
        if not data:
            raise ValueError("resume image must not be empty")
        total_bytes += len(data)
        if total_bytes >= 10 * 1024 * 1024:
            raise ValueError("combined resume image payload must remain below 10MB")
        encoded = base64.b64encode(data).decode("ascii")
        urls.append(f"data:{_image_mime(data)};base64,{encoded}")
    if llm_provider() != "fireworks" or not llm_active():
        raise RuntimeError("Fireworks image extraction requires an active configured provider")
    body = build_extraction_body(
        model_id=resolve_resume_model(model_id),
        resume_text="image resume",
        image_urls=urls,
    )
    raw = await run_fireworks_chat_body(body, session_id=session_id)
    try:
        extraction = ExtractedResume.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Fireworks image response failed ExtractedResume validation") from exc
    return extraction, {"mode": "fireworks_vision", "model": body["model"], "pages": len(urls)}


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF"):
        return "image/webp"
    guessed = mimetypes.guess_type("resume.bin")[0]
    return guessed or "image/png"


def normalize_extracted_skills(
    extraction: ExtractedResume,
    *,
    mapper: SkillOntologyMapper | None = None,
) -> list[NormalizedSkill]:
    """Normalize the model's explicit skill list without expanding its claims."""
    return (mapper or SkillOntologyMapper()).normalize(extraction.skills)
