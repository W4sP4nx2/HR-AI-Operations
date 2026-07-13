"""No-network tests for the explicitly gated scanned-resume VLM path."""

from __future__ import annotations

import asyncio
import json

import pytest

from pipelines.intake import CapabilityUnavailable
from services import resume_vlm


def test_resume_vlm_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(resume_vlm.settings, "enable_resume_vlm", False)

    with pytest.raises(CapabilityUnavailable, match="disabled"):
        asyncio.run(resume_vlm.parse_resume_pdf(b"%PDF-fixture"))


def test_resume_vlm_validates_schema_and_excludes_contact_from_scoring(monkeypatch):
    from core import llm_factory

    monkeypatch.setattr(resume_vlm.settings, "enable_resume_vlm", True)
    monkeypatch.setattr(resume_vlm.settings, "fireworks_vision_model", "tenant/vision-model")
    monkeypatch.setattr(resume_vlm.settings, "resume_vlm_max_pages", 4)
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fixture-fireworks-key-1234567890")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://inference.example.invalid/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/vision-model")
    monkeypatch.setattr(
        resume_vlm,
        "render_pdf_pages",
        lambda _data, *, max_pages: ["data:image/png;base64,AAAA"],
    )

    async def fake_request(body, **_kwargs):
        assert body["model"] == "tenant/vision-model"
        return json.dumps(
            {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "415-555-1234",
                "skills": ["Python", "FastAPI"],
                "experience": [
                    {
                        "company": "Example",
                        "title": "Engineer",
                        "start_date": "2022",
                        "end_date": None,
                        "summary": "Built Python services",
                    }
                ],
                "education": ["BSc"],
                "warnings": [],
            }
        )

    monkeypatch.setattr(llm_factory, "run_fireworks_chat_body", fake_request)
    extraction, metadata = asyncio.run(resume_vlm.parse_resume_pdf(b"%PDF-fixture"))
    screening_text = resume_vlm.extraction_to_screening_text(extraction)

    assert metadata == {"mode": "fireworks_vlm", "pages": 1, "warnings": 0}
    assert "Python" in screening_text
    assert "jane@example.com" not in screening_text
    assert "415-555-1234" not in screening_text


def test_resume_vlm_rejects_malformed_structured_output(monkeypatch):
    from core import llm_factory

    monkeypatch.setattr(resume_vlm.settings, "enable_resume_vlm", True)
    monkeypatch.setattr(resume_vlm.settings, "fireworks_vision_model", "tenant/vision-model")
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fixture-fireworks-key-1234567890")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://inference.example.invalid/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/vision-model")
    monkeypatch.setattr(
        resume_vlm,
        "render_pdf_pages",
        lambda _data, *, max_pages: ["data:image/png;base64,AAAA"],
    )

    async def malformed(_body, **_kwargs):
        return '{"name":"Jane"}'

    monkeypatch.setattr(llm_factory, "run_fireworks_chat_body", malformed)
    with pytest.raises(RuntimeError, match="schema validation"):
        asyncio.run(resume_vlm.parse_resume_pdf(b"%PDF-fixture"))
