"""Collect a non-secret hackathon evidence bundle.

The collector records command output exactly as text/JSON files so the demo team
can hand judges a reproducible packet. It never prints environment variable
values itself; provider smoke tests are delegated to the existing guarded scripts.

Examples:
  python scripts/collect_hackathon_evidence.py --profile static
  python scripts/collect_hackathon_evidence.py --profile fireworks-auth
  python scripts/collect_hackathon_evidence.py --profile amd-gemma \
    --amd-runtime-evidence /tmp/amd-runtime.json
  python scripts/audit_hackathon_readiness.py hackathon-evidence/<timestamp>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

Profile = Literal["static", "fireworks-auth", "amd-gemma", "full"]


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _prepare_output_dir(out_dir: Path) -> None:
    """Create a fresh output directory and reject stale evidence."""
    if out_dir.exists():
        if not out_dir.is_dir():
            raise RuntimeError(f"evidence output is not a directory: {out_dir}")
        if any(out_dir.iterdir()):
            raise RuntimeError(
                "evidence output directory must be empty; use a new timestamped directory"
            )
        return
    out_dir.mkdir(parents=True, exist_ok=False)


def _profile_env(provider: Literal["fireworks", "amd_vllm"]) -> dict[str, str]:
    """Build provider-specific overrides without exposing secret values."""
    env = {"LLM_PROVIDER": provider}
    if provider == "fireworks":
        models = os.environ.get("FIREWORKS_ALLOWED_MODELS") or os.environ.get("ALLOWED_MODELS")
        backend = os.environ.get("FIREWORKS_BACKEND_BASE_URL") or os.environ.get("BACKEND_BASE_URL")
    else:
        models = (
            os.environ.get("AMD_VLLM_ALLOWED_MODELS")
            or os.environ.get("AMD_VLLM_SERVED_MODEL")
            or os.environ.get("ALLOWED_MODELS")
        )
        backend = os.environ.get("AMD_BACKEND_BASE_URL") or os.environ.get("BACKEND_BASE_URL")
    if models:
        env["ALLOWED_MODELS"] = models
    if backend:
        env["BACKEND_BASE_URL"] = backend
    return env


def _validate_full_profile_environment() -> None:
    """Require two live backends so the full profile can prove both providers."""
    fireworks_backend = os.environ.get("FIREWORKS_BACKEND_BASE_URL", "").rstrip("/")
    amd_backend = os.environ.get("AMD_BACKEND_BASE_URL", "").rstrip("/")
    errors: list[str] = []
    if not os.environ.get("FIREWORKS_ALLOWED_MODELS", "").strip():
        errors.append("FIREWORKS_ALLOWED_MODELS is required for --profile full")
    if not (
        os.environ.get("AMD_VLLM_ALLOWED_MODELS", "").strip()
        or os.environ.get("AMD_VLLM_SERVED_MODEL", "").strip()
    ):
        errors.append(
            "AMD_VLLM_ALLOWED_MODELS or AMD_VLLM_SERVED_MODEL is required for --profile full"
        )
    if not fireworks_backend or not amd_backend:
        errors.append(
            "FIREWORKS_BACKEND_BASE_URL and AMD_BACKEND_BASE_URL are required for --profile full"
        )
    elif fireworks_backend == amd_backend:
        errors.append("the Fireworks and AMD backend base URLs must be different")
    if errors:
        raise RuntimeError("; ".join(errors))


def _run(
    name: str,
    command: list[str],
    *,
    cwd: Path = ROOT,
    out_dir: Path,
    required: bool = True,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=180,
        env=process_env,
    )
    output = {
        "name": name,
        "command": command,
        "cwd": str(cwd.relative_to(ROOT)),
        "returncode": completed.returncode,
        "required": required,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    (out_dir / f"{name}.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"[{status}] {name}")
    if required and completed.returncode != 0:
        raise RuntimeError(f"{name} failed")
    return output


def collect(
    profile: Profile,
    out_dir: Path,
    *,
    amd_runtime_evidence: Path | None = None,
) -> list[dict[str, object]]:
    if profile in ("amd-gemma", "full"):
        if amd_runtime_evidence is None:
            raise RuntimeError("--amd-runtime-evidence is required for AMD live proof")
        if not amd_runtime_evidence.is_file():
            raise RuntimeError(f"AMD runtime evidence not found: {amd_runtime_evidence}")
    if profile == "full":
        _validate_full_profile_environment()
    _prepare_output_dir(out_dir)
    results: list[dict[str, object]] = []

    static_commands = [
        (
            "docs-links",
            [sys.executable, "scripts/check_docs.py"],
            ROOT,
        ),
        (
            "platform-manifests",
            [sys.executable, "scripts/verify_platform_manifests.py"],
            ROOT,
        ),
        (
            "amd-gemma-overlay",
            [sys.executable, "scripts/verify_amd_gemma_overlay.py"],
            ROOT,
        ),
        (
            "amd-judge-preflight",
            [sys.executable, "scripts/preflight_amd_gemma_judge.py", "--mode", "static"],
            ROOT,
        ),
        (
            "completion-audit",
            [sys.executable, "scripts/verify_hackathon_completion_audit.py"],
            ROOT,
        ),
        (
            "cost-control-certification",
            [sys.executable, "-m", "scripts.certify_cost_controls", "--json"],
            BACKEND,
        ),
        (
            "grounding-control-certification",
            [sys.executable, "-m", "scripts.certify_grounding_controls", "--json"],
            BACKEND,
        ),
        (
            "frontend-lint",
            ["npm", "run", "lint"],
            ROOT / "frontend",
        ),
        (
            "provider-routing-tests",
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "pytest_asyncio.plugin",
                "tests/test_orchestrator.py",
                "tests/test_agent_contracts.py",
                "tests/test_admin_bootstrap.py",
                "tests/test_cost_control_certifier.py",
                "tests/test_grounding_control_certifier.py",
                "tests/test_grounding_guardrails.py",
                "tests/test_llm_factory.py",
                "tests/test_input_shield_byok.py",
                "tests/test_fireworks_workloads.py",
                "tests/test_fireworks_prepare_batch.py",
                "tests/test_byok_smoke.py",
                "tests/test_amd_vllm_smoke.py",
                "tests/test_amd_runtime_evidence.py",
                "tests/test_amd_gemma_judge_preflight.py",
                "tests/test_verify_hackathon_env.py",
                "tests/test_hackathon_completion_audit.py",
                "tests/test_evidence_manifest_verifier.py",
                "tests/test_hackathon_evidence_collector.py",
                "tests/test_hackathon_readiness_audit.py",
                "tests/test_api_integration.py::test_health_envelope_and_security_headers",
                "-q",
            ],
            BACKEND,
        ),
    ]

    for name, command, cwd in static_commands:
        env = {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"} if name.endswith("-tests") else None
        results.append(_run(name, command, cwd=cwd, out_dir=out_dir, env=env))

    if profile in ("fireworks-auth", "full"):
        fireworks_env = _profile_env("fireworks")
        results.append(
            _run(
                "fireworks-auth-env",
                [
                    sys.executable,
                    "-m",
                    "scripts.verify_hackathon_env",
                    "--mode",
                    "fireworks-auth",
                    "--json",
                ],
                cwd=BACKEND,
                out_dir=out_dir,
                env=fireworks_env,
            )
        )
        results.append(
            _run(
                "fireworks-smoke",
                [
                    sys.executable,
                    "-m",
                    "scripts.fireworks_smoke",
                    "--enable-cost-tracking",
                ],
                cwd=BACKEND,
                out_dir=out_dir,
                env=fireworks_env,
            )
        )
        results.append(
            _run(
                "fireworks-byok-smoke",
                [
                    sys.executable,
                    "-m",
                    "scripts.byok_smoke",
                    "--provider",
                    "fireworks",
                    "--json",
                ],
                cwd=BACKEND,
                out_dir=out_dir,
                env=fireworks_env,
            )
        )

    if profile in ("amd-gemma", "full"):
        amd_env = _profile_env("amd_vllm")
        assert amd_runtime_evidence is not None
        runtime_copy = out_dir / "amd-runtime.json"
        shutil.copyfile(amd_runtime_evidence, runtime_copy)
        results.append(
            _run(
                "amd-runtime-evidence",
                [
                    sys.executable,
                    "scripts/verify_amd_runtime_evidence.py",
                    str(runtime_copy),
                    "--json",
                ],
                cwd=ROOT,
                out_dir=out_dir,
            )
        )
        results.append(
            _run(
                "amd-gemma-env",
                [
                    sys.executable,
                    "-m",
                    "scripts.verify_hackathon_env",
                    "--mode",
                    "amd-gemma",
                    "--json",
                ],
                cwd=BACKEND,
                out_dir=out_dir,
                env=amd_env,
            )
        )
        results.append(
            _run(
                "amd-vllm-smoke",
                [sys.executable, "-m", "scripts.amd_vllm_smoke", "--json"],
                cwd=BACKEND,
                out_dir=out_dir,
                env=amd_env,
            )
        )
        results.append(
            _run(
                "amd-gemma-kustomize-render",
                ["kubectl", "kustomize", "deploy/k8s/overlays/amd-gemma"],
                cwd=ROOT,
                out_dir=out_dir,
            )
        )

    return results


def write_claims_markdown(out_dir: Path, readiness_result: dict[str, object]) -> Path:
    """Write a human-readable claims summary from readiness-audit JSON output."""
    stdout = str(readiness_result.get("stdout") or "")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("readiness-audit did not emit valid JSON") from exc

    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise RuntimeError("readiness-audit JSON did not contain a claims list")

    lines = [
        "# Hackathon Claims Summary",
        "",
        "Generated from `scripts/audit_hackathon_readiness.py`.",
        "",
        "Submission hooks: **Fireworks powered** auth, **Gemma powered** / "
        "**Gamma powered** model routing, and an **AMD powered** deployment "
        "profile. Treat live provider and hardware claims as valid only when "
        "their status is `proven`.",
        "",
        "| Claim | Status | Evidence | Safe wording |",
        "|---|---|---|---|",
    ]
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        evidence = claim.get("evidence")
        evidence_text = (
            ", ".join(str(item) for item in evidence) if isinstance(evidence, list) else ""
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(str(claim.get("name") or "")),
                    _md_cell(str(claim.get("status") or "")),
                    _md_cell(evidence_text or "none"),
                    _md_cell(str(claim.get("safe_wording") or "")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Live provider and AMD hardware claims are valid only when their status is `proven`.",
            "",
        ]
    )
    path = out_dir / "CLAIMS.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_evidence_manifest(out_dir: Path) -> Path:
    """Write file names, byte sizes and SHA-256 hashes for generated evidence."""
    manifest_path = out_dir / "EVIDENCE_MANIFEST.json"
    files: list[dict[str, object]] = []
    for path in sorted(out_dir.iterdir()):
        if not path.is_file() or path.name == manifest_path.name:
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": path.name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "file_count": len(files),
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def verify_evidence_manifest(out_dir: Path) -> None:
    """Fail collection if the final evidence manifest cannot verify the bundle."""
    verifier_path = ROOT / "scripts" / "verify_evidence_manifest.py"
    spec = importlib.util.spec_from_file_location("verify_evidence_manifest", verifier_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"could not load evidence manifest verifier from {verifier_path}")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    verify = verifier.verify

    errors = verify(out_dir)
    if errors:
        raise RuntimeError("evidence manifest verification failed: " + "; ".join(errors))


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=["static", "fireworks-auth", "amd-gemma", "full"],
        default="static",
        help="Evidence profile to collect.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "hackathon-evidence" / _timestamp(),
        help="Output directory for JSON evidence files.",
    )
    parser.add_argument(
        "--amd-runtime-evidence",
        type=Path,
        help=(
            "JSON created by capture_amd_runtime_evidence.py; required for "
            "amd-gemma and full profiles"
        ),
    )
    args = parser.parse_args()

    try:
        results = collect(
            args.profile,
            args.out,
            amd_runtime_evidence=args.amd_runtime_evidence,
        )
    except RuntimeError as exc:
        print(f"Evidence collection failed: {exc}", file=sys.stderr)
        print(f"Partial evidence: {args.out}")
        return 1

    summary = {
        "profile": args.profile,
        "generated_at": datetime.now(UTC).isoformat(),
        "results": [
            {
                "name": result["name"],
                "returncode": result["returncode"],
                "required": result["required"],
            }
            for result in results
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    readiness_result = _run(
        "readiness-audit",
        [
            sys.executable,
            "scripts/audit_hackathon_readiness.py",
            str(args.out),
            "--json",
        ],
        cwd=ROOT,
        out_dir=args.out,
    )
    try:
        claims_path = write_claims_markdown(args.out, readiness_result)
    except RuntimeError as exc:
        print(f"Evidence collection failed: {exc}", file=sys.stderr)
        print(f"Partial evidence: {args.out}")
        return 1
    manifest_path = write_evidence_manifest(args.out)
    try:
        verify_evidence_manifest(args.out)
    except RuntimeError as exc:
        print(f"Evidence collection failed: {exc}", file=sys.stderr)
        print(f"Partial evidence: {args.out}")
        return 1
    print(f"Claims summary written to {claims_path}")
    print(f"Evidence manifest written to {manifest_path}")
    print("Evidence manifest verification passed")
    print(f"Evidence bundle written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
