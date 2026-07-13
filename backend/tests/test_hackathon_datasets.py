"""Synthetic governance dataset generator tests."""

from __future__ import annotations

import asyncio
import csv
import json

import core.memory as memmod
from api.routes import metrics
from core.bias_audit import audit_hiring_csv
from core.config import settings
from core.memory import Memory
from pipelines.ingestion import ingest_pdf
from scripts import upload_resume_dump
from scripts.certify_hackathon_synthetic_data import certify
from scripts.generate_hackathon_datasets import generate_all
from scripts.load_poisoned_policies import load_and_probe
from scripts.upload_resume_dump import build_upload_plan
from services import local_vector_store
from services.rag import _apply_active_policy_version_filter, _apply_title_boost


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_hackathon_dataset_generator_creates_required_traps(tmp_path):
    outputs = generate_all(
        tmp_path,
        ats_records=400,
        guardrail_questions=16,
        resumes=5,
        seed=42,
    )

    policy_rows = _read_csv(outputs["poisoned_policy_manifest"])
    pto_2024 = [row for row in policy_rows if row["doc_id"] == "policy_pto_2024"]
    pto_2023 = [row for row in policy_rows if row["doc_id"] == "policy_pto_2023"]
    assert len(policy_rows) == 40
    assert pto_2024[0]["status"] == "active"
    assert pto_2024[0]["expected_active_fact"] == "Employees get 25 days PTO per calendar year."
    assert pto_2024[0]["must_cite_doc_id"] == "policy_pto_2024"
    assert pto_2023[0]["status"] == "expired"

    pto_chunks = ingest_pdf(
        str(tmp_path / "poisoned_policies" / "policy_pto_2024.pdf"),
        doc_id="policy_pto_2024",
    )
    metadata = pto_chunks[0]["metadata"]
    assert {
        key: metadata[key]
        for key in {
            "source",
            "effective_date",
            "expires_on",
            "status",
            "policy_family",
            "policy_version",
            "chunk_index",
        }
    } == {
        "source": str(tmp_path / "poisoned_policies" / "policy_pto_2024.pdf"),
        "effective_date": "2024-01-01",
        "expires_on": "",
        "status": "active",
        "policy_family": "policy_pto",
        "policy_version": 2024,
        "chunk_index": 0,
    }
    assert metadata["chunk_strategy"] == "fixed"
    assert metadata["chunking_plan"]["goal"] == "policy_retrieval"

    ats_rows = _read_csv(outputs["adverse_impact_ats"])
    assert len(ats_rows) == 400
    summary = json.loads(
        (tmp_path / "adverse_impact_ats" / "four_fifths_expected_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["black_vs_white_ratio"] < 0.80
    assert summary["violates_four_fifths_rule"] is True

    guardrail_rows = _read_csv(outputs["pii_injection_stress"])
    expected = {row["expected_guardrail"] for row in guardrail_rows}
    assert "redact_ssn_before_audit_and_provider" in expected
    assert "block_prompt_injection" in expected

    resume_rows = _read_csv(outputs["resume_manifest"])
    assert len(resume_rows) == 5
    assert all(
        (tmp_path / "resume_pdf_dump" / "pdfs" / row["filename"]).exists() for row in resume_rows
    )
    batch_manifest = tmp_path / "resume_pdf_dump" / "fireworks_resume_vision_batch_manifest.jsonl"
    assert len(batch_manifest.read_text(encoding="utf-8").splitlines()) == 5


def test_four_fifths_auditor_flags_generated_ats_dump(tmp_path):
    outputs = generate_all(
        tmp_path,
        ats_records=400,
        guardrail_questions=16,
        resumes=5,
        seed=42,
    )

    audit = audit_hiring_csv(outputs["adverse_impact_ats"])
    race = next(item for item in audit["dimensions"] if item["dimension"] == "race")

    assert audit["record_count"] == 400
    assert audit["violates_four_fifths_rule"] is True
    assert race["lowest_group"] == "Black"
    assert race["adverse_impact_ratio"] < 0.80
    assert "adverse-impact alert" in audit["headline"]


def test_metrics_bias_audit_endpoint_uses_auditor_payload(monkeypatch, tmp_path):
    outputs = generate_all(
        tmp_path,
        ats_records=400,
        guardrail_questions=16,
        resumes=5,
        seed=42,
    )
    monkeypatch.setattr(metrics, "DEFAULT_SYNTHETIC_ATS_PATH", outputs["adverse_impact_ats"])

    import asyncio

    payload = asyncio.run(metrics.get_bias_audit({}))

    assert payload["success"] is True
    assert payload["data"]["available"] is True
    assert payload["data"]["violates_four_fifths_rule"] is True


def test_poisoned_policy_retrieval_discards_expired_version():
    hits = [
        {
            "doc_id": "policy_pto_2023",
            "score": 0.99,
            "text": "Employees get 15 days PTO.",
        },
        {
            "doc_id": "policy_pto_2024",
            "score": 0.91,
            "text": "Employees get 25 days PTO.",
        },
        {
            "doc_id": "policy_remote_work_2024.pdf",
            "score": 0.55,
            "text": "Remote work remains active.",
        },
    ]

    filtered = _apply_active_policy_version_filter(hits)

    assert [hit["doc_id"] for hit in filtered] == [
        "policy_pto_2024",
        "policy_remote_work_2024.pdf",
    ]
    assert "25 days PTO" in filtered[0]["text"]


def test_policy_retrieval_uses_temporal_metadata_not_filename_order():
    hits = [
        {
            "doc_id": "legacy-copy-without-year",
            "score": 0.99,
            "text": "Employees get 15 days PTO.",
            "metadata": {
                "policy_family": "policy_pto",
                "effective_date": "2023-01-01",
                "expires_on": "2023-12-31",
                "status": "expired",
            },
        },
        {
            "doc_id": "current-copy-without-year",
            "score": 0.72,
            "text": "Employees get 25 days PTO.",
            "metadata": {
                "policy_family": "policy_pto",
                "effective_date": "2024-01-01",
                "expires_on": "",
                "status": "active",
            },
        },
    ]

    filtered = _apply_active_policy_version_filter(hits)

    assert [hit["doc_id"] for hit in filtered] == ["current-copy-without-year"]


def test_pto_title_boost_beats_generic_leave_policy():
    hits = [
        {"doc_id": "annual_leave_policy", "score": 0.95, "text": "20 annual leave days"},
        {"doc_id": "policy_pto_2024", "score": 0.60, "text": "25 days PTO"},
    ]

    boosted = _apply_title_boost("How many PTO days do I have?", hits)

    assert boosted[0]["doc_id"] == "policy_pto_2024"
    assert boosted[0]["score"] == 0.97


def test_hackathon_synthetic_data_certifier_passes(tmp_path):
    result = certify(tmp_path)

    assert result["ok"] is True
    assert result["passed_count"] == result["gate_count"] == 5
    gate_names = {gate["name"] for gate in result["gates"]}
    assert {
        "poisoned_policy_versioning",
        "four_fifths_bias_audit",
        "pii_redaction_and_injection_block",
        "resume_pdf_batch_manifest",
        "resume_object_storage_plan",
    } == gate_names


def test_hashing_embedding_provider_bypasses_model_loader(monkeypatch):
    import core.embeddings as embeddings

    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setattr(
        embeddings,
        "_load_model",
        lambda: (_ for _ in ()).throw(AssertionError("model loader should not run")),
    )

    vector = embeddings.Embedder().embed("How many PTO days do I have?")

    assert len(vector) == embeddings._FALLBACK_DIM
    assert embeddings.Embedder().provider == "hashing"


def test_resume_dump_upload_plan_targets_s3_objects(tmp_path):
    outputs = generate_all(
        tmp_path,
        ats_records=40,
        guardrail_questions=8,
        resumes=3,
        seed=42,
    )

    plan = build_upload_plan(
        tmp_path / "resume_pdf_dump" / "resume_manifest.csv",
        bucket="hrcc-synthetic-resumes",
        prefix="demo",
    )

    assert len(plan) == 3
    assert plan[0]["uri"].startswith("s3://hrcc-synthetic-resumes/demo/candidate-")
    assert plan[0]["size_bytes"] > 0
    assert len(plan[0]["sha256"]) == 64
    assert outputs["resume_manifest"].endswith("resume_manifest.csv")


def test_resume_upload_verifies_every_planned_object(monkeypatch, tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    plan = [
        {
            "bucket": "test-bucket",
            "key": "batch/first.pdf",
            "uri": "s3://test-bucket/batch/first.pdf",
            "local_path": str(first),
        },
        {
            "bucket": "test-bucket",
            "key": "batch/second.pdf",
            "uri": "s3://test-bucket/batch/second.pdf",
            "local_path": str(second),
        },
    ]
    monkeypatch.setattr(upload_resume_dump, "_s3_put", lambda **_kwargs: None)
    monkeypatch.setattr(
        upload_resume_dump,
        "_s3_list_objects",
        lambda **_kwargs: {
            "keys": ["batch/first.pdf", "batch/second.pdf"],
            "total_bytes": 11,
        },
    )

    result = upload_resume_dump.upload_plan(
        plan,
        endpoint="http://minio:9000",
        access_key="test-key",
        secret_key="test-secret",
        region="us-east-1",
        create_bucket=False,
    )

    assert result["uploaded"] == 2
    assert result["verification"] == {
        "ok": True,
        "expected_objects": 2,
        "listed_objects": 2,
        "missing_count": 0,
        "unexpected_count": 0,
        "total_bytes": 11,
        "first_missing_keys": [],
        "first_unexpected_keys": [],
    }


def test_load_poisoned_policies_probes_active_rag_backend(monkeypatch, tmp_path):
    outputs = generate_all(
        tmp_path,
        ats_records=40,
        guardrail_questions=8,
        resumes=3,
        seed=42,
    )
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashing")

    saved_memory = memmod.memory
    saved_mock_llm = settings.mock_llm
    saved_ready = local_vector_store.local_vector_store._ready
    try:
        memmod.memory = Memory(f"sqlite:///{tmp_path / 'rag_probe.db'}")
        settings.mock_llm = True
        local_vector_store.local_vector_store._ready = False
        result = asyncio.run(load_and_probe(tmp_path / "poisoned_policies", require_pgvector=False))
    finally:
        asyncio.run(memmod.memory.engine.dispose())
        memmod.memory = saved_memory
        settings.mock_llm = saved_mock_llm
        local_vector_store.local_vector_store._ready = saved_ready

    assert result["passes_pto_trap"] is True
    assert result["winning_doc_id"] == "policy_pto_2024"
    assert result["source_doc_ids"][0] == "policy_pto_2024"
    assert outputs["poisoned_policy_manifest"].endswith("synthetic_policy_manifest.csv")
