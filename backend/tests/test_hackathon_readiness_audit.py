"""No-network tests for hackathon evidence readiness classification."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = ROOT / "scripts" / "audit_hackathon_readiness.py"
SPEC = importlib.util.spec_from_file_location("audit_hackathon_readiness", AUDIT_SCRIPT)
assert SPEC and SPEC.loader
readiness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = readiness
SPEC.loader.exec_module(readiness)

assert readiness


def _write_result(directory: Path, name: str, returncode: int = 0) -> None:
    (directory / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "command": ["fixture"],
                "cwd": ".",
                "returncode": returncode,
                "required": True,
                "stdout": "",
                "stderr": "",
            }
        ),
        encoding="utf-8",
    )


def _claim_statuses(directory: Path) -> dict[str, str]:
    return {claim.name: claim.status for claim in readiness.audit(directory)}


def test_static_bundle_is_proven_with_live_claims_gated(tmp_path) -> None:
    for name in readiness.STATIC_REQUIRED:
        _write_result(tmp_path, name)

    statuses = _claim_statuses(tmp_path)

    assert statuses["Static product readiness"] == "proven"
    assert statuses["Fireworks API auth path"] == "live_gated"
    assert statuses["AMD-hosted Gemma deployment"] == "live_gated"
    assert statuses["Safe submission wording"] == "proven"


def test_full_live_bundle_proves_fireworks_and_amd_claims(tmp_path) -> None:
    for name in readiness.STATIC_REQUIRED | readiness.FIREWORKS_LIVE | readiness.AMD_LIVE:
        _write_result(tmp_path, name)

    statuses = _claim_statuses(tmp_path)

    assert statuses["Static product readiness"] == "proven"
    assert statuses["Fireworks API auth path"] == "proven"
    assert statuses["AMD-hosted Gemma deployment"] == "proven"
    assert statuses["Safe submission wording"] == "proven"


def test_failed_static_gate_blocks_static_readiness(tmp_path) -> None:
    for name in readiness.STATIC_REQUIRED:
        _write_result(tmp_path, name, returncode=1 if name == "completion-audit" else 0)

    statuses = _claim_statuses(tmp_path)

    assert statuses["Static product readiness"] == "failed"
    assert "Safe submission wording" not in statuses
