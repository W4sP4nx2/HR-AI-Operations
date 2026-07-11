"""Batch preparation accepts JSONL and demographically blinded PDF records."""

from __future__ import annotations

import json

import pytest

from scripts.fireworks_prepare_batch import (
    BATCH_RESPONSE_SCHEMA,
    _build_batch_jsonl,
    _certify_batch_results,
    _custom_id,
    _load_json_records,
    _resolve_model_id,
    _text_records_from_directory,
)


def test_load_jsonl_records_and_ids_are_stable(tmp_path):
    source = tmp_path / "records.jsonl"
    source.write_text(
        '{"custom_id":"a","prompt":"one"}\n{"custom_id":"b","prompt":"two"}\n',
        encoding="utf-8",
    )

    records = _load_json_records(source)

    assert [item["custom_id"] for item in records] == ["a", "b"]
    custom_id = _custom_id(3, tmp_path / "Jane Doe.pdf")
    assert custom_id.startswith("resume-00003-")
    assert "Jane" not in custom_id


def test_pdf_directory_requires_job_description(tmp_path):
    (tmp_path / "resume.pdf").write_bytes(b"not read because validation runs first")

    with pytest.raises(SystemExit, match="job-description"):
        _text_records_from_directory(tmp_path, "")


def test_batch_builder_rejects_duplicate_custom_ids(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/batch-model")
    source = tmp_path / "records.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps({"custom_id": "duplicate", "prompt": "one"}),
                json.dumps({"custom_id": "duplicate", "prompt": "two"}),
            ]
        ),
        encoding="utf-8",
    )
    from core.fireworks import build_batch_jsonl

    with pytest.raises(ValueError, match="duplicate custom_id"):
        build_batch_jsonl(
            _load_json_records(source),
            model_id="tenant/batch-model",
            system_prompt="Return JSON.",
        )


def test_batch_rows_use_strict_json_schema_contract():
    payload = _build_batch_jsonl(
        [{"custom_id": "resume-1", "prompt": "Screen this resume."}],
        model="tenant/batch-model",
        system_prompt="Return JSON.",
        max_tokens=400,
    )
    row = json.loads(payload)
    response_format = row["body"]["response_format"]

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "ResumeScreeningBatchResult"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == BATCH_RESPONSE_SCHEMA
    assert row["body"]["temperature"] == 0


def test_batch_results_are_split_by_certification():
    records = [
        {
            "custom_id": "good",
            "response": json.dumps(
                {
                    "score": 81,
                    "recommendation": "review",
                    "matched_skills": ["python"],
                    "missing_skills": [],
                    "reasoning": "Relevant experience.",
                    "confidence": 0.88,
                }
            ),
        },
        {
            "custom_id": "bad",
            "response": json.dumps(
                {
                    "score": 101,
                    "recommendation": "email jane@example.com",
                    "matched_skills": [],
                    "missing_skills": [],
                    "reasoning": "Bad range and PII.",
                }
            ),
        },
    ]

    certified, failed = _certify_batch_results(records)

    assert [row["custom_id"] for row in certified] == ["good"]
    assert certified[0]["certified"] is True
    assert [row["custom_id"] for row in failed] == ["bad"]
    assert failed[0]["certified"] is False


def test_batch_model_requires_explicit_arg_or_allowed_models(monkeypatch):
    monkeypatch.delenv("ALLOWED_MODELS", raising=False)
    with pytest.raises(SystemExit, match="Model ID required"):
        _resolve_model_id("")

    monkeypatch.setenv("ALLOWED_MODELS", "tenant/first,tenant/second")
    assert _resolve_model_id("") == "tenant/first"
    assert _resolve_model_id("tenant/explicit") == "tenant/explicit"
