"""Capture non-secret AMD ROCm/PyTorch/vLLM runtime identity as JSON.

The probe can run in the current Python environment, the AMD Docker Compose
service, or the Kubernetes inference deployment. It records device names,
memory, and software versions; it does not record environment variables,
credentials, prompts, or model outputs.

Examples:
  python scripts/capture_amd_runtime_evidence.py --target local --out /tmp/amd-runtime.json
  python scripts/capture_amd_runtime_evidence.py --target docker-compose --out /tmp/amd-runtime.json
  python scripts/capture_amd_runtime_evidence.py --target kubernetes --out /tmp/amd-runtime.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from verify_amd_runtime_evidence import validate

ROOT = Path(__file__).resolve().parents[1]
Target = Literal["local", "docker-compose", "kubernetes"]

PROBE = """
import importlib.metadata
import json
import platform
import torch

try:
    vllm_version = importlib.metadata.version("vllm")
except importlib.metadata.PackageNotFoundError:
    vllm_version = ""

count = torch.cuda.device_count() if torch.cuda.is_available() else 0
devices = []
for index in range(count):
    properties = torch.cuda.get_device_properties(index)
    devices.append({
        "index": index,
        "name": torch.cuda.get_device_name(index),
        "total_memory_bytes": int(properties.total_memory),
    })
print(json.dumps({
    "python_version": platform.python_version(),
    "torch_version": str(torch.__version__),
    "rocm_version": str(torch.version.hip or ""),
    "vllm_version": vllm_version,
    "torch_cuda_available": bool(torch.cuda.is_available()),
    "device_count": count,
    "devices": devices,
}))
""".strip()


def probe_command(
    target: Target,
    *,
    namespace: str,
    deployment: str,
    container: str,
) -> list[str]:
    """Build the fixed, non-shell command for one capture target."""
    if target == "local":
        return [sys.executable, "-c", PROBE]
    if target == "docker-compose":
        return [
            "docker",
            "compose",
            "-f",
            "docker-compose.prod.yml",
            "-f",
            "docker-compose.amd.yml",
            "--profile",
            "amd",
            "exec",
            "-T",
            "amd-vllm",
            "python3",
            "-c",
            PROBE,
        ]
    return [
        "kubectl",
        "-n",
        namespace,
        "exec",
        f"deploy/{deployment}",
        "-c",
        container,
        "--",
        "python3",
        "-c",
        PROBE,
    ]


def capture(
    target: Target,
    *,
    namespace: str = "hr-ai-system",
    deployment: str = "hrcc-gpu-inference",
    container: str = "inference",
    timeout: float = 30.0,
) -> dict[str, object]:
    """Run the probe and return a validated, non-secret evidence payload."""
    command = probe_command(
        target,
        namespace=namespace,
        deployment=deployment,
        container=container,
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "probe failed"
        raise RuntimeError(detail[-2000:])
    try:
        runtime = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AMD runtime probe did not emit valid JSON") from exc
    if not isinstance(runtime, dict):
        raise RuntimeError("AMD runtime probe did not emit a JSON object")

    payload: dict[str, object] = {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "capture_target": target,
        **runtime,
    }
    errors = validate(payload)
    if errors:
        raise RuntimeError("; ".join(errors))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=["local", "docker-compose", "kubernetes"],
        required=True,
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--namespace", default="hr-ai-system")
    parser.add_argument("--deployment", default="hrcc-gpu-inference")
    parser.add_argument("--container", default="inference")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    try:
        payload = capture(
            args.target,
            namespace=args.namespace,
            deployment=args.deployment,
            container=args.container,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - operator-facing capture command
        print(f"AMD runtime evidence capture failed: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"AMD runtime evidence written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
