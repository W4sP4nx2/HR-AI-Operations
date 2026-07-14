"""Contract tests for the objective's resume pipeline building blocks."""

from __future__ import annotations

import io
import json
import zipfile

import pytest


def _make_pdf(text: str) -> bytes:
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        None,
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    stream = b"BT /F1 18 Tf 72 700 Td (" + text.encode() + b") Tj ET"
    objects[3] = b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream"
    pdf = b"%PDF-1.4\n"
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += str(index).encode() + b" 0 obj" + obj + b"endobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join((f"{offset:010d} 00000 n \n".encode() for offset in offsets))
    pdf += b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n" + str(xref).encode() + b"\n%%EOF"
    return pdf


def _make_docx(text: str) -> bytes:
    document_xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body></w:document>"
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return output.getvalue()


def test_parser_handles_pdf_docx_html_json_and_text() -> None:
    from services.resume_pipeline import ResumeParserPipeline

    parser = ResumeParserPipeline()
    pdf = parser.parse(_make_pdf("Senior Python Engineer FastAPI"), "resume.pdf")
    assert pdf.source_type == "pdf_text"
    assert "FastAPI" in pdf.text

    docx = parser.parse(_make_docx("Python and Kubernetes"), "resume.docx")
    assert docx.source_type == "docx"
    assert "Kubernetes" in docx.text

    html = parser.parse(
        b"<html><script>alert(1)</script><h1>Resume</h1><p>Python</p></html>", "resume.html"
    )
    assert html.source_type == "html"
    assert "alert" not in html.text
    assert "Python" in html.text

    linked_in = parser.parse(
        json.dumps({"headline": "Engineer", "skills": ["Python", "K8s"]}).encode(),
        "linkedin.json",
    )
    assert linked_in.source_type == "linkedin_json"
    assert "Engineer" in linked_in.text

    text = parser.parse(b"Plain text resume", "resume.txt")
    assert text.source_type == "text"


def test_parser_reports_password_and_legacy_doc_boundaries() -> None:
    from services.resume_pipeline import ResumeParseError, ResumeParserPipeline

    parser = ResumeParserPipeline()
    with pytest.raises(ResumeParseError):
        parser.parse(b"%PDF-not-a-real-pdf", "locked.pdf")
    with pytest.raises(Exception, match="doc_parser"):
        parser.parse(b"legacy binary", "resume.doc")


def test_legacy_doc_uses_only_the_sandboxed_converter(monkeypatch) -> None:
    import subprocess

    from services import resume_pipeline

    monkeypatch.setattr(
        resume_pipeline.shutil,
        "which",
        lambda name: "/usr/bin/antiword" if name == "antiword" else None,
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(
            command, 0, stdout=b"Converted Python resume", stderr=b""
        )

    monkeypatch.setattr(resume_pipeline.subprocess, "run", fake_run)
    parsed = resume_pipeline.ResumeParserPipeline().parse(b"legacy binary", "resume.doc")
    assert parsed.source_type == "doc"
    assert "Converted Python" in parsed.text
    assert calls and calls[0][0] == "/usr/bin/antiword"


def test_scanned_image_has_explicit_vision_fallback_when_ocr_is_unavailable() -> None:
    from services.resume_pipeline import ResumeParserPipeline

    parsed = ResumeParserPipeline().parse(b"\x89PNG\r\n\x1a\nnot-a-real-image", "scan.png")
    assert parsed.source_type == "image"
    assert parsed.needs_vision_fallback
    assert "vision_fallback_required" in parsed.warnings


def test_skill_ontology_normalizes_aliases_and_scores_overlap() -> None:
    from services.skill_normalizer import SkillOntologyMapper

    mapper = SkillOntologyMapper()
    normalized = mapper.normalize(["py", "Python3", "k8s", "unknown-tool"])
    names = {item.name for item in normalized}
    assert "Python" in names
    assert "Kubernetes" in names
    assert "Unknown-Tool" in names
    assert mapper.calculate_match_score(normalized, ["Python", "Kubernetes"]) == 1.0


def test_quality_checker_returns_recruiter_reviewable_grade() -> None:
    from services.resume_extractor import ExtractedExperience, ExtractedResume
    from services.resume_quality import ResumeQualityChecker

    resume = ExtractedResume(
        email="candidate@example.com",
        work_experience=[
            ExtractedExperience(
                company="Acme",
                title="Engineer",
                start_date="2020-01",
                end_date="2022-01",
                skills_used=["Python"],
            )
        ],
        skills=["Python"],
        warnings=["ambiguous date"],
    )
    report = ResumeQualityChecker().check(resume)
    assert report.grade in {"A", "B", "C", "D", "F"}
    assert report.needs_human_review
    assert "Missing phone number" in report.issues


def test_extraction_body_is_strict_and_allowlisted(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_MODELS", "accounts/fireworks/models/gemma-4-demo")
    from services.resume_extractor import EXTRACTED_RESUME_SCHEMA, build_extraction_body

    body = build_extraction_body(
        model_id="accounts/fireworks/models/gemma-4-demo",
        resume_text="Python engineer",
    )
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == EXTRACTED_RESUME_SCHEMA
    assert body["temperature"] == 0.1


def test_batch_processor_prepares_mixed_files_and_skips_bad_inputs(tmp_path) -> None:
    from services.resume_batch_processor import ResumeBatchProcessor

    good = tmp_path / "good.pdf"
    good.write_bytes(_make_pdf("Python engineer with FastAPI"))
    bad = tmp_path / "bad.doc"
    bad.write_bytes(b"legacy")
    processor = ResumeBatchProcessor()
    manifest = processor.prepare(
        [good, bad],
        job_description="Python engineer",
        model_id="accounts/fireworks/models/gemma-4-demo",
    )
    assert len(manifest.records) == 1
    assert len(manifest.skipped) == 1
    payload = processor.to_jsonl(manifest, model_id="accounts/fireworks/models/gemma-4-demo")
    row = json.loads(payload)
    assert row["custom_id"].startswith("resume-")
    assert row["body"]["response_format"]["json_schema"]["strict"] is True


def test_batch_processor_chunks_records_without_reordering(tmp_path) -> None:
    from services.resume_batch_processor import ResumeBatchProcessor

    files = []
    for index in range(3):
        path = tmp_path / f"resume-{index}.txt"
        path.write_text(f"Python engineer {index}", encoding="utf-8")
        files.append(path)
    processor = ResumeBatchProcessor(batch_size=2)
    manifest = processor.prepare(files, job_description="Python", model_id="tenant/model")
    batches = list(processor.iter_batches(manifest))
    assert [len(batch.records) for batch in batches] == [2, 1]
    assert [record.source_ref for batch in batches for record in batch.records] == [
        "resume-0.txt",
        "resume-1.txt",
        "resume-2.txt",
    ]


def test_batch_processor_submits_bounded_jobs_without_exposing_credentials(
    monkeypatch, tmp_path
) -> None:
    import asyncio

    from services import fireworks_batch
    from services.resume_batch_processor import ResumeBatchProcessor

    files = []
    for index in range(3):
        path = tmp_path / f"resume-{index}.txt"
        path.write_text(f"Python engineer {index}", encoding="utf-8")
        files.append(path)
    processor = ResumeBatchProcessor(batch_size=2)
    manifest = processor.prepare(files, job_description="Python", model_id="tenant/model")
    events: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, _config):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def create_dataset(self, dataset_id):
            events.append(("dataset", dataset_id))
            return {}

        async def upload_jsonl(self, dataset_id, payload, *, filename):
            assert dataset_id.endswith("input")
            assert payload and filename.endswith(".jsonl")
            events.append(("upload", dataset_id))
            return {}

        async def create_job(self, **kwargs):
            events.append(("job", kwargs["job_id"]))
            return {}

    monkeypatch.setattr(fireworks_batch.BatchConfig, "from_env", classmethod(lambda cls: object()))
    monkeypatch.setattr(fireworks_batch, "FireworksBatchClient", FakeClient)
    submissions = asyncio.run(
        processor.submit_batches(manifest, model_id="tenant/model", job_prefix="demo batch")
    )
    assert [item.records for item in submissions] == [2, 1]
    assert len([event for event in events if event[0] == "job"]) == 2
    assert "fixture-fireworks-key-not-real" not in repr(submissions)
