"""Generate a no-secret Dynamic Capability Engine evidence package.

This command is safe before live API keys exist. It performs no provider calls,
captures the current capability registry, runs zero-spend cost certification,
and writes a JSON artifact operators can attach to a hackathon submission or
pre-live review.

Usage:
  python -m scripts.generate_capability_evidence --output capability-evidence.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def build_package() -> dict[str, Any]:
    """Build a no-secret capability evidence package."""
    from core.capability_registry import capability_snapshot
    from scripts.certify_cost_controls import run_certification

    capabilities = capability_snapshot()
    cost_controls = run_certification()
    package = {
        "schema": "hrcc.capability_evidence.v1",
        "generated_at_unix": time.time(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "env_presence": _redacted_env_summary(),
        },
        "capabilities": capabilities,
        "cost_controls": cost_controls,
        "claim_boundary": {
            "no_provider_calls": True,
            "no_secret_values": True,
            "live_fireworks_claim": _claim_status(capabilities, "fireworks"),
            "live_amd_gemma_claim": _claim_status(capabilities, "amd_vllm_gemma"),
            "performance_claims": "not_claimed_without_live_benchmark_artifacts",
        },
        "next_live_inputs": capabilities["required_live_inputs"],
    }
    package["package_sha256"] = _digest_without_self_hash(package)
    return package


def write_package(output: Path) -> dict[str, Any]:
    """Write package to ``output`` and return it."""
    package = build_package()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return package


def _claim_status(capabilities: dict[str, Any], provider_id: str) -> str:
    provider = next(
        (item for item in capabilities["providers"] if item["provider_id"] == provider_id),
        None,
    )
    if provider is None:
        return "not_present"
    if provider["status"] == "proven":
        return "proven"
    if provider["live_enabled"]:
        return "configured_live_smoke_required"
    return "live_gated"


def _digest_without_self_hash(package: dict[str, Any]) -> str:
    copy = dict(package)
    copy.pop("package_sha256", None)
    encoded = json.dumps(copy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redacted_env_summary() -> dict[str, str]:
    """Return only presence/absence for relevant env, never values."""
    keys = [
        "LLM_PROVIDER",
        "FIREWORKS_API_KEY",
        "FIREWORKS_BASE_URL",
        "ALLOWED_MODELS",
        "AMD_VLLM_BASE_URL",
        "AMD_VLLM_API_KEY",
        "AMD_VLLM_SERVED_MODEL",
        "AMD_RUNTIME_EVIDENCE_FILE",
    ]
    return {key: "set" if os.environ.get(key, "").strip() else "unset" for key in keys}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("capability-evidence.json"),
        help="Destination JSON file.",
    )
    parser.add_argument("--json", action="store_true", help="Print package JSON to stdout too.")
    args = parser.parse_args(argv)

    package = write_package(args.output)
    if args.json:
        print(json.dumps(package, indent=2, sort_keys=True))
    else:
        print(f"Wrote capability evidence: {args.output}")
        print(f"cost_controls_ok={package['cost_controls']['ok']}")
        print(f"fireworks_claim={package['claim_boundary']['live_fireworks_claim']}")
        print(f"amd_gemma_claim={package['claim_boundary']['live_amd_gemma_claim']}")
    return 0 if package["cost_controls"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
