"""No-network tests for the hackathon completion-audit verifier."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_hackathon_completion_audit.py"
SPEC = importlib.util.spec_from_file_location("verify_hackathon_completion_audit", SCRIPT)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)

assert verifier


def _write_valid_audit(path: Path) -> None:
    rows = "\n".join(f"| {row} | Implemented | evidence |" for row in verifier.REQUIRED_MATRIX_ROWS)
    path.write_text(
        "\n".join(
            [
                "# Audit",
                *verifier.REQUIRED_AUDIT_PHRASES,
                "| Blueprint requirement | Current status | Authoritative evidence |",
                "|---|---|---|",
                rows,
            ]
        ),
        encoding="utf-8",
    )


def _write_valid_guarded_doc(path: Path) -> None:
    path.write_text("\n".join(verifier.REQUIRED_GUARDED_PHRASES), encoding="utf-8")


def _write_valid_judge_brief(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                *verifier.REQUIRED_JUDGE_BRIEF_PHRASES,
                *verifier.REQUIRED_GUARDED_PHRASES,
            ]
        ),
        encoding="utf-8",
    )


def _write_valid_claims(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                *verifier.REQUIRED_CLAIMS_PHRASES,
                *verifier.REQUIRED_GUARDED_PHRASES,
            ]
        ),
        encoding="utf-8",
    )


def test_completion_audit_verifier_passes_for_required_matrix(monkeypatch, tmp_path) -> None:
    audit = tmp_path / "HACKATHON_COMPLETION_AUDIT.md"
    claims = tmp_path / "CLAIMS.md"
    judge = tmp_path / "HACKATHON_JUDGE_BRIEF.md"
    guarded_one = tmp_path / "HACKATHON_GEMMA_AMD_DEPLOYMENT.md"
    guarded_two = tmp_path / "COMPETITIVE_QUALITY_GATE.md"
    _write_valid_audit(audit)
    _write_valid_claims(claims)
    _write_valid_judge_brief(judge)
    _write_valid_guarded_doc(guarded_one)
    _write_valid_guarded_doc(guarded_two)

    monkeypatch.setattr(verifier, "AUDIT_DOC", audit)
    monkeypatch.setattr(verifier, "CLAIMS_DOC", claims)
    monkeypatch.setattr(verifier, "JUDGE_BRIEF", judge)
    monkeypatch.setattr(verifier, "GUARDED_DOCS", [claims, judge, guarded_one, guarded_two])

    assert verifier.verify() == []


def test_completion_audit_rejects_browser_persisted_byok(monkeypatch, tmp_path) -> None:
    audit = tmp_path / "HACKATHON_COMPLETION_AUDIT.md"
    claims = tmp_path / "CLAIMS.md"
    judge = tmp_path / "HACKATHON_JUDGE_BRIEF.md"
    guarded = tmp_path / "HACKATHON_GEMMA_AMD_DEPLOYMENT.md"
    frontend_api = tmp_path / "api.ts"
    _write_valid_audit(audit)
    _write_valid_claims(claims)
    _write_valid_judge_brief(judge)
    _write_valid_guarded_doc(guarded)
    frontend_api.write_text(
        "\n".join(
            [
                "let inMemoryByokKey: string | null = null;",
                "window.sessionStorage.setItem('byok', inMemoryByokKey || '');",
                "export function authHeaders() {}",
                "export function inferenceHeaders() {}",
                'headers["X-Client-LLM-Key"] = byok;',
                "/** Build ordinary application headers",
                "async function request() { authHeaders(); }",
                "async function inferenceRequest() { inferenceHeaders(); }",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(verifier, "AUDIT_DOC", audit)
    monkeypatch.setattr(verifier, "CLAIMS_DOC", claims)
    monkeypatch.setattr(verifier, "JUDGE_BRIEF", judge)
    monkeypatch.setattr(verifier, "GUARDED_DOCS", [claims, judge, guarded])
    monkeypatch.setattr(verifier, "FRONTEND_API", frontend_api)

    assert "frontend BYOK key must not use Web Storage" in verifier.verify()


def test_completion_audit_verifier_fails_when_live_gates_are_removed(monkeypatch, tmp_path) -> None:
    audit = tmp_path / "HACKATHON_COMPLETION_AUDIT.md"
    claims = tmp_path / "CLAIMS.md"
    judge = tmp_path / "HACKATHON_JUDGE_BRIEF.md"
    guarded = tmp_path / "HACKATHON_GEMMA_AMD_DEPLOYMENT.md"
    _write_valid_audit(audit)
    _write_valid_claims(claims)
    _write_valid_judge_brief(judge)
    guarded.write_text("provider=fireworks\nprovider=amd_vllm", encoding="utf-8")

    monkeypatch.setattr(verifier, "AUDIT_DOC", audit)
    monkeypatch.setattr(verifier, "CLAIMS_DOC", claims)
    monkeypatch.setattr(verifier, "JUDGE_BRIEF", judge)
    monkeypatch.setattr(verifier, "GUARDED_DOCS", [guarded])

    errors = verifier.verify()

    assert any("guarded docs missing phrase: benchmark" in error for error in errors)


def test_completion_audit_verifier_fails_when_matrix_row_is_missing(monkeypatch, tmp_path) -> None:
    audit = tmp_path / "HACKATHON_COMPLETION_AUDIT.md"
    claims = tmp_path / "CLAIMS.md"
    judge = tmp_path / "HACKATHON_JUDGE_BRIEF.md"
    guarded = tmp_path / "HACKATHON_GEMMA_AMD_DEPLOYMENT.md"
    _write_valid_audit(audit)
    audit.write_text(
        audit.read_text(encoding="utf-8").replace(
            "Zero-spend cost governance before API calls",
            "cost governance",
        ),
        encoding="utf-8",
    )
    _write_valid_claims(claims)
    _write_valid_judge_brief(judge)
    _write_valid_guarded_doc(guarded)

    monkeypatch.setattr(verifier, "AUDIT_DOC", audit)
    monkeypatch.setattr(verifier, "CLAIMS_DOC", claims)
    monkeypatch.setattr(verifier, "JUDGE_BRIEF", judge)
    monkeypatch.setattr(verifier, "GUARDED_DOCS", [claims, judge, guarded])

    errors = verifier.verify()

    assert any("Zero-spend cost governance before API calls" in error for error in errors)


def test_completion_audit_verifier_fails_when_judge_brief_loses_thesis(
    monkeypatch, tmp_path
) -> None:
    audit = tmp_path / "HACKATHON_COMPLETION_AUDIT.md"
    claims = tmp_path / "CLAIMS.md"
    judge = tmp_path / "HACKATHON_JUDGE_BRIEF.md"
    guarded = tmp_path / "HACKATHON_GEMMA_AMD_DEPLOYMENT.md"
    _write_valid_audit(audit)
    _write_valid_claims(claims)
    _write_valid_guarded_doc(guarded)
    judge.write_text("CLAIMS.md\nbenchmark\nprovider=fireworks", encoding="utf-8")

    monkeypatch.setattr(verifier, "AUDIT_DOC", audit)
    monkeypatch.setattr(verifier, "CLAIMS_DOC", claims)
    monkeypatch.setattr(verifier, "JUDGE_BRIEF", judge)
    monkeypatch.setattr(verifier, "GUARDED_DOCS", [claims, judge, guarded])

    errors = verifier.verify()

    assert any("judge brief missing phrase" in error for error in errors)


def test_completion_audit_verifier_fails_when_claims_ledger_is_missing(
    monkeypatch, tmp_path
) -> None:
    audit = tmp_path / "HACKATHON_COMPLETION_AUDIT.md"
    claims = tmp_path / "CLAIMS.md"
    judge = tmp_path / "HACKATHON_JUDGE_BRIEF.md"
    guarded = tmp_path / "HACKATHON_GEMMA_AMD_DEPLOYMENT.md"
    _write_valid_audit(audit)
    _write_valid_judge_brief(judge)
    _write_valid_guarded_doc(guarded)

    monkeypatch.setattr(verifier, "AUDIT_DOC", audit)
    monkeypatch.setattr(verifier, "CLAIMS_DOC", claims)
    monkeypatch.setattr(verifier, "JUDGE_BRIEF", judge)
    monkeypatch.setattr(verifier, "GUARDED_DOCS", [claims, judge, guarded])

    errors = verifier.verify()

    assert "missing CLAIMS.md" in errors
