"""Audit a hackathon evidence bundle into safe and gated claims.

This script does not run tests. It reads the JSON files produced by
``collect_hackathon_evidence.py`` and answers a simpler question:

  "What can we honestly claim from this bundle?"

Use it after collecting static or live evidence:

  python scripts/audit_hackathon_readiness.py /path/to/evidence-dir
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Status = Literal["proven", "live_gated", "missing", "failed"]


@dataclass(frozen=True)
class Claim:
    name: str
    status: Status
    evidence: list[str]
    safe_wording: str


STATIC_REQUIRED = {
    "docs-links",
    "platform-manifests",
    "amd-gemma-overlay",
    "amd-judge-preflight",
    "completion-audit",
    "cost-control-certification",
    "grounding-control-certification",
    "frontend-lint",
    "provider-routing-tests",
}
FIREWORKS_LIVE = {"fireworks-auth-env", "fireworks-smoke", "fireworks-byok-smoke"}
AMD_LIVE = {
    "amd-runtime-evidence",
    "amd-gemma-env",
    "amd-vllm-smoke",
    "amd-gemma-kustomize-render",
}


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - operator-facing diagnostics
        return {"name": path.stem, "returncode": 1, "error": str(exc)}
    if isinstance(value, dict):
        return value
    return {"name": path.stem, "returncode": 1, "error": "not a JSON object"}


def _commands(evidence_dir: Path) -> dict[str, dict]:
    commands: dict[str, dict] = {}
    for path in sorted(evidence_dir.glob("*.json")):
        if path.name == "summary.json":
            continue
        payload = _load_json(path)
        name = str(payload.get("name") or path.stem)
        commands[name] = payload
    return commands


def _passed(commands: dict[str, dict], names: set[str]) -> set[str]:
    return {name for name in names if int(commands.get(name, {}).get("returncode", 1)) == 0}


def _status(commands: dict[str, dict], names: set[str]) -> Status:
    present = names & commands.keys()
    passed = _passed(commands, names)
    if passed == names:
        return "proven"
    if present and any(int(commands[name].get("returncode", 1)) != 0 for name in present):
        return "failed"
    return "missing"


def audit(evidence_dir: Path) -> list[Claim]:
    commands = _commands(evidence_dir)
    static_passed = _passed(commands, STATIC_REQUIRED)
    static_status = _status(commands, STATIC_REQUIRED)
    fireworks_status = _status(commands, FIREWORKS_LIVE)
    amd_status = _status(commands, AMD_LIVE)

    claims: list[Claim] = [
        Claim(
            name="Static product readiness",
            status=static_status,
            evidence=sorted(static_passed),
            safe_wording=(
                "Static docs, frontend, provider-routing, BYOK, and AMD-Gemma "
                "deployment-contract checks pass, with zero-spend cost controls "
                "and grounding controls certified separately from live provider "
                "and hardware proof."
            ),
        ),
        Claim(
            name="Fireworks API auth path",
            status=fireworks_status if fireworks_status != "missing" else "live_gated",
            evidence=sorted(_passed(commands, FIREWORKS_LIVE)),
            safe_wording=(
                "Fireworks auth follows the OpenAI-compatible quickstart contract; "
                "live credential acceptance is proven only when fireworks-smoke passes."
            ),
        ),
        Claim(
            name="AMD-hosted Gemma deployment",
            status=amd_status if amd_status != "missing" else "live_gated",
            evidence=sorted(_passed(commands, AMD_LIVE)),
            safe_wording=(
                "The repo is deployable to an AMD/vLLM Gemma route; real AMD hosting "
                "is proven only when named AMD device/ROCm/vLLM runtime evidence, "
                "amd-vllm-smoke, and the rendered overlay all pass."
            ),
        ),
    ]

    if (
        static_status == "proven"
        and fireworks_status in ("proven", "missing")
        and amd_status
        in (
            "proven",
            "missing",
        )
    ):
        claims.append(
            Claim(
                name="Safe submission wording",
                status="proven",
                evidence=sorted(static_passed),
                safe_wording=(
                    "Fireworks-authenticated and AMD-Gemma deployable; live provider "
                    "and hardware performance claims remain gated by smoke/benchmark evidence."
                ),
            )
        )
    return claims


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args()

    if not args.evidence_dir.exists():
        print(f"Evidence directory not found: {args.evidence_dir}", file=sys.stderr)
        return 2

    claims = audit(args.evidence_dir)
    if args.json:
        print(
            json.dumps(
                {
                    "evidence_dir": str(args.evidence_dir),
                    "claims": [
                        {
                            "name": claim.name,
                            "status": claim.status,
                            "evidence": claim.evidence,
                            "safe_wording": claim.safe_wording,
                        }
                        for claim in claims
                    ],
                },
                indent=2,
            )
        )
    else:
        for claim in claims:
            print(f"[{claim.status.upper()}] {claim.name}")
            if claim.evidence:
                print(f"  evidence: {', '.join(claim.evidence)}")
            print(f"  wording: {claim.safe_wording}")

    blocking_failures = [claim.name for claim in claims if claim.status == "failed"]
    if blocking_failures:
        print("Failed evidence gates: " + ", ".join(blocking_failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
