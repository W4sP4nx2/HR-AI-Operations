"""No-network contracts for the live ETL integration certifier."""

from __future__ import annotations

import asyncio
from pathlib import Path

from scripts import certify_etl_integrations as certifier


def _plan() -> list[dict[str, str]]:
    return [
        {
            "bucket": "hrcc-synthetic-resumes",
            "key": f"candidate-{index:04d}.pdf",
            "uri": f"s3://hrcc-synthetic-resumes/candidate-{index:04d}.pdf",
        }
        for index in range(1_000)
    ]


def test_live_etl_certifier_combines_pgvector_and_minio_evidence(monkeypatch) -> None:
    async def fake_policy_probe(*_args, **_kwargs):
        return {
            "backend": "pgvector",
            "chunks_loaded": 40,
            "winning_doc_id": "policy_pto_2024",
            "passes_pto_trap": True,
        }

    async def fake_storage():
        return {
            "pgvector_extension_version": "0.8.2",
            "synthetic_policy_chunks": 40,
            "pto_metadata": {
                "policy_pto_2023": {
                    "status": "expired",
                    "expires_on": "2023-12-31",
                },
                "policy_pto_2024": {
                    "status": "active",
                    "effective_date": "2024-01-01",
                },
            },
        }

    plan = _plan()
    monkeypatch.setattr(certifier, "load_and_probe", fake_policy_probe)
    monkeypatch.setattr(certifier, "_pgvector_storage_evidence", fake_storage)
    monkeypatch.setattr(certifier, "build_upload_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(
        certifier,
        "_s3_list_objects",
        lambda **_kwargs: {
            "keys": [row["key"] for row in plan],
            "total_bytes": 1_083_447,
        },
    )

    result = asyncio.run(
        certifier.certify_integrations(
            corpus_dir=Path("policies"),
            resume_manifest=Path("resumes.csv"),
            endpoint="http://127.0.0.1:9000",
            bucket="hrcc-synthetic-resumes",
            prefix="",
            access_key="test-key",
            secret_key="test-secret",
            region="us-east-1",
        )
    )

    assert result["ok"] is True
    assert result["passed_count"] == result["gate_count"] == 2
    assert result["gates"][0]["evidence"]["winning_doc_id"] == "policy_pto_2024"
    assert result["gates"][1]["evidence"]["listed_objects"] == 1_000
    assert "test-key" not in str(result)
    assert "test-secret" not in str(result)


def test_object_storage_gate_fails_when_manifest_object_is_missing() -> None:
    plan = _plan()
    listing = {
        "keys": [row["key"] for row in plan[:-1]],
        "total_bytes": 1_000,
    }

    gate = certifier._object_storage_gate(plan, listing, "http://127.0.0.1:9000")

    assert gate["ok"] is False
    assert gate["evidence"]["expected_objects"] == 1_000
    assert gate["evidence"]["listed_objects"] == 999
    assert gate["evidence"]["missing_count"] == 1
