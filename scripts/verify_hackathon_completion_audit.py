"""Static completion-audit guard for hackathon claims.

This verifier protects the repo from accidentally presenting the Fireworks or
AMD-hosted Gemma track as fully complete without live provider and hardware
evidence. It checks both the requirement-by-requirement completion audit and
the judge-facing guarded-claim docs.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DOC = ROOT / "HACKATHON_COMPLETION_AUDIT.md"
JUDGE_BRIEF = ROOT / "HACKATHON_JUDGE_BRIEF.md"
CLAIMS_DOC = ROOT / "CLAIMS.md"
FRONTEND_API = ROOT / "frontend" / "lib" / "api.ts"
GUARDED_DOCS = [
    CLAIMS_DOC,
    JUDGE_BRIEF,
    ROOT / "HACKATHON_GEMMA_AMD_DEPLOYMENT.md",
    ROOT / "COMPETITIVE_QUALITY_GATE.md",
]

REQUIRED_AUDIT_PHRASES = (
    "blueprint-complete and static-evidence complete",
    "not live-certified",
    "Fireworks live proof",
    "AMD/Gemma live proof",
    "capture_amd_runtime_evidence.py",
    "preflight_amd_gemma_judge.py",
    "Published performance claims",
    "live provider and hardware performance claims remain gated",
)

REQUIRED_MATRIX_ROWS = (
    "Senior thesis: governed A2A control plane, not chatbot demo",
    "Fireworks-first pivot while keeping AMD/Gemma route",
    "Model IDs not hardcoded; route only from allowlist",
    "A2A agent cards and tool-visible routing metadata",
    "Certified A2A envelopes for cross-agent handoff",
    "Constrained structured output path",
    "Zero-spend cost governance before API calls",
    "RAG over policy chunks instead of full-PDF stuffing",
    "Request-scoped, route-scoped BYOK key handling",
    "Provider credential trust boundaries",
    "Enforced-auth first administrator bootstrap",
    "Fireworks Batch preparation and status control plane",
    "Human-in-the-loop for sensitive workflows",
    "AMD-hosted Gemma deployment profile",
)

REQUIRED_JUDGE_BRIEF_PHRASES = (
    "HR AI Command Center is a governed, cost-bounded A2A control plane",
    "Route cheaply",
    "Retrieve narrowly",
    "Constrain outputs",
    "Attribute spend",
    "Escalate safely",
    "CLAIMS.md",
    "capture_amd_runtime_evidence.py",
    "preflight_amd_gemma_judge.py",
    "Fireworks-authenticated and AMD-Gemma deployable",
)

REQUIRED_CLAIMS_PHRASES = (
    "Hackathon Claims Ledger",
    "Fireworks powered",
    "Gemma powered",
    "Gamma powered",
    "AMD powered",
    "Fireworks quickstart base URL",
    "AMD powered runtime is real",
    "capture_amd_runtime_evidence.py",
    "preflight_amd_gemma_judge.py",
    "Live-gated",
)

REQUIRED_GUARDED_PHRASES = (
    "gated",
    "provider=fireworks",
    "provider=amd_vllm",
    "amd_vllm_smoke",
    "capture_amd_runtime_evidence.py",
    "fireworks_smoke",
    "do not claim amd latency",
    "smoke",
    "benchmark",
    "amd powered",
    "gemma powered",
    "gamma powered",
    "fireworks powered",
    "browser byok is disabled",
)

REQUIRED_BYOK_PHRASES = (
    "let inMemoryByokKey",
    "export function inferenceHeaders",
    'headers["X-Client-LLM-Key"] = byok',
)


def _normalized(text: str) -> str:
    """Collapse whitespace and lowercase for resilient Markdown checks."""
    return " ".join(text.lower().split())


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def verify() -> list[str]:
    errors: list[str] = []
    if not AUDIT_DOC.exists():
        return ["missing HACKATHON_COMPLETION_AUDIT.md"]

    audit_text = _normalized(AUDIT_DOC.read_text(encoding="utf-8"))
    for phrase in REQUIRED_AUDIT_PHRASES:
        if _normalized(phrase) not in audit_text:
            errors.append(f"completion audit missing phrase: {phrase}")
    for row in REQUIRED_MATRIX_ROWS:
        if _normalized(row) not in audit_text:
            errors.append(f"completion audit missing matrix row: {row}")

    if not JUDGE_BRIEF.exists():
        errors.append("missing HACKATHON_JUDGE_BRIEF.md")
    else:
        judge_text = _normalized(JUDGE_BRIEF.read_text(encoding="utf-8"))
        for phrase in REQUIRED_JUDGE_BRIEF_PHRASES:
            if _normalized(phrase) not in judge_text:
                errors.append(f"judge brief missing phrase: {phrase}")

    if not CLAIMS_DOC.exists():
        errors.append("missing CLAIMS.md")
    else:
        claims_text = _normalized(CLAIMS_DOC.read_text(encoding="utf-8"))
        for phrase in REQUIRED_CLAIMS_PHRASES:
            if _normalized(phrase) not in claims_text:
                errors.append(f"claims ledger missing phrase: {phrase}")

    missing_docs = [_display_path(path) for path in GUARDED_DOCS if not path.exists()]
    if missing_docs:
        errors.extend(f"missing guarded-claim doc: {path}" for path in missing_docs)
        return errors

    guarded_text = _normalized("\n".join(path.read_text(encoding="utf-8") for path in GUARDED_DOCS))
    for phrase in REQUIRED_GUARDED_PHRASES:
        if _normalized(phrase) not in guarded_text:
            errors.append(f"guarded docs missing phrase: {phrase}")

    if not FRONTEND_API.exists():
        errors.append("missing frontend/lib/api.ts")
    else:
        frontend_text = FRONTEND_API.read_text(encoding="utf-8")
        for phrase in REQUIRED_BYOK_PHRASES:
            if phrase not in frontend_text:
                errors.append(f"frontend BYOK implementation missing phrase: {phrase}")
        start = frontend_text.find("let inMemoryByokKey")
        end = frontend_text.find("/** Build ordinary application headers", start)
        byok_store = frontend_text[start:end] if start >= 0 and end > start else ""
        if "localStorage" in byok_store or "sessionStorage" in byok_store:
            errors.append("frontend BYOK key must not use Web Storage")
        auth_start = frontend_text.find("export function authHeaders")
        inference_start = frontend_text.find("export function inferenceHeaders", auth_start)
        auth_block = (
            frontend_text[auth_start:inference_start]
            if auth_start >= 0 and inference_start > auth_start
            else ""
        )
        if "X-Client-LLM-Key" in auth_block:
            errors.append("ordinary frontend auth headers must not include BYOK")
        request_start = frontend_text.find("async function request")
        inference_request_start = frontend_text.find("async function inferenceRequest")
        request_block = (
            frontend_text[request_start:inference_request_start]
            if request_start >= 0 and inference_request_start > request_start
            else ""
        )
        if "authHeaders" not in request_block or "inferenceHeaders" in request_block:
            errors.append("ordinary frontend requests must use authHeaders without BYOK")

    return errors


def main() -> int:
    errors = verify()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Hackathon completion audit passes static evidence-map checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
