"""No-network tests for evidence manifest verification."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_SCRIPT = ROOT / "scripts" / "collect_hackathon_evidence.py"
VERIFIER_SCRIPT = ROOT / "scripts" / "verify_evidence_manifest.py"

COLLECTOR_SPEC = importlib.util.spec_from_file_location(
    "collect_hackathon_evidence", COLLECTOR_SCRIPT
)
assert COLLECTOR_SPEC and COLLECTOR_SPEC.loader
collector = importlib.util.module_from_spec(COLLECTOR_SPEC)
sys.modules[COLLECTOR_SPEC.name] = collector
COLLECTOR_SPEC.loader.exec_module(collector)

VERIFIER_SPEC = importlib.util.spec_from_file_location("verify_evidence_manifest", VERIFIER_SCRIPT)
assert VERIFIER_SPEC and VERIFIER_SPEC.loader
verifier = importlib.util.module_from_spec(VERIFIER_SPEC)
sys.modules[VERIFIER_SPEC.name] = verifier
VERIFIER_SPEC.loader.exec_module(verifier)

assert collector and verifier


def test_evidence_manifest_verifier_accepts_matching_hashes(tmp_path) -> None:
    (tmp_path / "CLAIMS.md").write_text("# Claims", encoding="utf-8")
    (tmp_path / "summary.json").write_text('{"ok": true}', encoding="utf-8")
    collector.write_evidence_manifest(tmp_path)

    assert verifier.verify(tmp_path) == []


def test_evidence_manifest_verifier_rejects_tampered_file(tmp_path) -> None:
    (tmp_path / "CLAIMS.md").write_text("# Claims", encoding="utf-8")
    collector.write_evidence_manifest(tmp_path)
    (tmp_path / "CLAIMS.md").write_text("# Changed", encoding="utf-8")

    errors = verifier.verify(tmp_path)

    assert any("sha256 mismatch" in error for error in errors)


def test_evidence_manifest_verifier_rejects_extra_file(tmp_path) -> None:
    (tmp_path / "CLAIMS.md").write_text("# Claims", encoding="utf-8")
    collector.write_evidence_manifest(tmp_path)
    (tmp_path / "extra.json").write_text("{}", encoding="utf-8")

    errors = verifier.verify(tmp_path)

    assert any("files missing from manifest: extra.json" in error for error in errors)


def test_evidence_manifest_verifier_rejects_unexpected_directory(tmp_path) -> None:
    (tmp_path / "CLAIMS.md").write_text("# Claims", encoding="utf-8")
    collector.write_evidence_manifest(tmp_path)
    (tmp_path / "nested").mkdir()

    errors = verifier.verify(tmp_path)

    assert any("unexpected directories in evidence bundle: nested" in error for error in errors)


def test_evidence_manifest_verifier_rejects_invalid_manifest_path(tmp_path) -> None:
    (tmp_path / "EVIDENCE_MANIFEST.json").write_text(
        json.dumps({"file_count": 1, "files": [{"path": "../secret", "bytes": 1, "sha256": "x"}]}),
        encoding="utf-8",
    )

    errors = verifier.verify(tmp_path)

    assert any("invalid manifest path" in error for error in errors)


def test_evidence_manifest_verifier_rejects_duplicate_rows(tmp_path) -> None:
    data = b"{}"
    digest = hashlib.sha256(data).hexdigest()
    (tmp_path / "summary.json").write_bytes(data)
    row = {"path": "summary.json", "bytes": len(data), "sha256": digest}
    (tmp_path / "EVIDENCE_MANIFEST.json").write_text(
        json.dumps({"file_count": 1, "files": [row, row]}),
        encoding="utf-8",
    )

    errors = verifier.verify(tmp_path)

    assert "duplicate manifest path: summary.json" in errors


def test_evidence_manifest_verifier_rejects_symlinks(tmp_path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    collector.write_evidence_manifest(tmp_path)
    target.unlink()
    target.symlink_to(tmp_path / "outside.json")

    errors = verifier.verify(tmp_path)

    assert "symbolic links are not allowed: target.json" in errors
