"""No-network tests for hackathon evidence bundle helpers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "collect_hackathon_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_hackathon_evidence", SCRIPT)
assert SPEC and SPEC.loader
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)

assert collector


def test_write_claims_markdown_summarizes_readiness_claims(tmp_path) -> None:
    readiness_result = {
        "stdout": json.dumps(
            {
                "claims": [
                    {
                        "name": "Static product readiness",
                        "status": "proven",
                        "evidence": ["docs-links", "completion-audit"],
                        "safe_wording": "Static checks pass.",
                    },
                    {
                        "name": "Fireworks API auth path",
                        "status": "live_gated",
                        "evidence": [],
                        "safe_wording": "Run fireworks-smoke.",
                    },
                ]
            }
        )
    }

    path = collector.write_claims_markdown(tmp_path, readiness_result)

    text = path.read_text(encoding="utf-8")
    assert "# Hackathon Claims Summary" in text
    assert "Fireworks powered" in text
    assert "Gemma powered" in text
    assert "Gamma powered" in text
    assert "AMD powered" in text
    assert "Static product readiness" in text
    assert "docs-links, completion-audit" in text
    assert "Fireworks API auth path" in text
    assert "live_gated" in text


def test_write_claims_markdown_rejects_invalid_readiness_json(tmp_path) -> None:
    try:
        collector.write_claims_markdown(tmp_path, {"stdout": "not-json"})
    except RuntimeError as exc:
        assert "valid JSON" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_write_evidence_manifest_hashes_generated_files(tmp_path) -> None:
    (tmp_path / "summary.json").write_text('{"ok": true}', encoding="utf-8")
    (tmp_path / "CLAIMS.md").write_text("# Claims", encoding="utf-8")

    path = collector.write_evidence_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["file_count"] == 2
    indexed = {row["path"]: row for row in payload["files"]}
    assert set(indexed) == {"CLAIMS.md", "summary.json"}
    assert indexed["CLAIMS.md"]["bytes"] == len("# Claims".encode("utf-8"))
    assert len(indexed["summary.json"]["sha256"]) == 64
    assert "EVIDENCE_MANIFEST.json" not in indexed


def test_verify_evidence_manifest_rejects_tampering(tmp_path) -> None:
    (tmp_path / "summary.json").write_text('{"ok": true}', encoding="utf-8")
    collector.write_evidence_manifest(tmp_path)
    (tmp_path / "summary.json").write_text('{"ok": false}', encoding="utf-8")

    try:
        collector.verify_evidence_manifest(tmp_path)
    except RuntimeError as exc:
        assert "sha256 mismatch" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_output_directory_must_be_empty(tmp_path) -> None:
    (tmp_path / "stale-live-proof.json").write_text("{}", encoding="utf-8")

    try:
        collector._prepare_output_dir(tmp_path)
    except RuntimeError as exc:
        assert "must be empty" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_provider_specific_environment_keeps_model_allowlists_separate(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_MODELS", "shared-model")
    monkeypatch.setenv("FIREWORKS_ALLOWED_MODELS", "accounts/fireworks/models/gemma")
    monkeypatch.setenv("AMD_VLLM_SERVED_MODEL", "amd-gemma-3-27b-it")
    monkeypatch.setenv("FIREWORKS_BACKEND_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("AMD_BACKEND_BASE_URL", "http://localhost:8002")

    fireworks = collector._profile_env("fireworks")
    amd = collector._profile_env("amd_vllm")

    assert fireworks == {
        "LLM_PROVIDER": "fireworks",
        "ALLOWED_MODELS": "accounts/fireworks/models/gemma",
        "BACKEND_BASE_URL": "http://localhost:8000",
    }
    assert amd == {
        "LLM_PROVIDER": "amd_vllm",
        "ALLOWED_MODELS": "amd-gemma-3-27b-it",
        "BACKEND_BASE_URL": "http://localhost:8002",
    }


def test_full_profile_requires_distinct_running_backends(monkeypatch) -> None:
    monkeypatch.setenv("FIREWORKS_ALLOWED_MODELS", "accounts/fireworks/models/gemma")
    monkeypatch.setenv("AMD_VLLM_SERVED_MODEL", "amd-gemma-3-27b-it")
    monkeypatch.setenv("FIREWORKS_BACKEND_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("AMD_BACKEND_BASE_URL", "http://localhost:8000")

    try:
        collector._validate_full_profile_environment()
    except RuntimeError as exc:
        assert "must be different" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
