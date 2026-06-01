"""Tests for the input intake layer and the response status contract.

These cover the three ways content enters the system (text / PDF / URL) and the
``ok`` / ``error`` / ``unavailable`` envelope used by the trigger button.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_pdf(text: str) -> bytes:
    """Build a minimal, valid single-page PDF containing ``text``."""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        None,  # content stream, filled below
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    stream = b"BT /F1 18 Tf 72 700 Td (" + text.encode() + b") Tj ET"
    objs[3] = b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream"

    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj" + obj + b"endobj\n"
    xref_pos = len(pdf)
    pdf += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += (
        b"trailer<</Size "
        + str(len(objs) + 1).encode()
        + b"/Root 1 0 R>>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF"
    )
    return pdf


# --------------------------------------------------------------------------- #
# Response status contract
# --------------------------------------------------------------------------- #
def test_response_status_contract() -> None:
    """ok/fail/unavailable must set both `success` and the `status` enum."""
    from api.responses import fail, ok, unavailable

    assert ok({"x": 1}) == {
        "success": True,
        "status": "ok",
        "data": {"x": 1},
        "error": None,
    }
    f = fail("bad input")
    assert f["success"] is False and f["status"] == "error"
    u = unavailable("scraper missing", {"capability": "scrape"})
    assert u["success"] is False and u["status"] == "unavailable"
    assert u["data"] == {"capability": "scrape"}


# --------------------------------------------------------------------------- #
# Intake: text
# --------------------------------------------------------------------------- #
def test_intake_text() -> None:
    """Plain text resolves to a text IntakeResult."""
    from pipelines.intake import resolve_input

    r = resolve_input(text="Need help with my benefits enrollment")
    assert r.source_type == "text"
    assert "benefits" in r.text
    assert r.as_dict()["source_type"] == "text"


def test_intake_empty_raises() -> None:
    """No input is a ValueError (maps to status=error)."""
    from pipelines.intake import resolve_input

    with pytest.raises(ValueError):
        resolve_input()
    with pytest.raises(ValueError):
        resolve_input(text="   ")


# --------------------------------------------------------------------------- #
# Intake: PDF
# --------------------------------------------------------------------------- #
def test_intake_pdf_extraction() -> None:
    """A valid PDF's text is extracted and normalised."""
    pytest.importorskip("pypdf")
    from pipelines.intake import resolve_input

    pdf = _make_pdf("Senior Python Engineer FastAPI PyTorch AWS")
    r = resolve_input(pdf_bytes=pdf, filename="resume.pdf")
    assert r.source_type == "pdf"
    assert r.source_ref == "resume.pdf"
    assert "FastAPI" in r.text and "PyTorch" in r.text


def test_intake_bad_pdf_raises_valueerror() -> None:
    """Garbage bytes are a ValueError, not a crash (maps to status=error)."""
    pytest.importorskip("pypdf")
    from pipelines.intake import resolve_input

    with pytest.raises(ValueError):
        resolve_input(pdf_bytes=b"not a pdf at all")


# --------------------------------------------------------------------------- #
# Intake: URL (scraper)
# --------------------------------------------------------------------------- #
def test_intake_url_bad_scheme() -> None:
    """Non-http(s) URLs are rejected as a ValueError."""
    from pipelines.intake import extract_text_from_url

    with pytest.raises(ValueError):
        extract_text_from_url("ftp://example.com/file")


def test_intake_url_unreachable_is_unavailable() -> None:
    """A fetch failure surfaces as CapabilityUnavailable (status=unavailable)."""
    from pipelines.intake import CapabilityUnavailable, extract_text_from_url

    with pytest.raises(CapabilityUnavailable):
        extract_text_from_url("http://nonexistent.invalid.host.example/", timeout=2.0)
