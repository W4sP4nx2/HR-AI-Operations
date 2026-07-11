"""Validate non-secret evidence that Gemma inference ran on AMD ROCm hardware.

The matching capture script records only runtime versions and device metadata.
This verifier intentionally does not treat a deployment manifest, model-server
URL, or latency number as proof of AMD hosting.

Usage:
  python scripts/verify_amd_runtime_evidence.py /path/to/amd-runtime.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CAPTURE_TARGETS = {"local", "docker-compose", "kubernetes"}
AMD_DEVICE_MARKERS = ("amd", "instinct", "radeon", "gfx", "mi2", "mi3")


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _looks_like_amd_device(name: object) -> bool:
    if not _nonempty_string(name):
        return False
    lowered = str(name).lower()
    return any(marker in lowered for marker in AMD_DEVICE_MARKERS)


def validate(payload: object) -> list[str]:
    """Return validation errors for an AMD runtime evidence payload."""
    if not isinstance(payload, dict):
        return ["evidence payload is not a JSON object"]

    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    captured_at = payload.get("captured_at")
    if not _nonempty_string(captured_at):
        errors.append("captured_at is missing")
    else:
        try:
            parsed = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                errors.append("captured_at must include a timezone")
        except ValueError:
            errors.append("captured_at is not a valid ISO-8601 timestamp")

    target = payload.get("capture_target")
    if target not in CAPTURE_TARGETS:
        errors.append("capture_target must be local, docker-compose, or kubernetes")

    for field in ("python_version", "torch_version", "rocm_version", "vllm_version"):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"{field} is missing")

    device_count = payload.get("device_count")
    if not isinstance(device_count, int) or isinstance(device_count, bool) or device_count < 1:
        errors.append("device_count must be a positive integer")

    devices = payload.get("devices")
    if not isinstance(devices, list) or not devices:
        errors.append("devices must contain at least one AMD device")
    else:
        if isinstance(device_count, int) and not isinstance(device_count, bool):
            if device_count != len(devices):
                errors.append("device_count does not match devices")
        for index, device in enumerate(devices):
            if not isinstance(device, dict):
                errors.append(f"devices[{index}] is not an object")
                continue
            if device.get("index") != index:
                errors.append(f"devices[{index}].index must be {index}")
            if not _nonempty_string(device.get("name")):
                errors.append(f"devices[{index}].name is missing")
            elif not _looks_like_amd_device(device.get("name")):
                errors.append(f"devices[{index}].name does not identify AMD hardware")
            memory = device.get("total_memory_bytes")
            if not isinstance(memory, int) or isinstance(memory, bool) or memory <= 0:
                errors.append(f"devices[{index}].total_memory_bytes must be positive")

    if payload.get("torch_cuda_available") is not True:
        errors.append("torch_cuda_available must be true for the ROCm PyTorch runtime")
    return errors


def load_and_validate(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load one JSON evidence file and return its payload and errors."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - operator-facing diagnostics
        return None, [f"could not read AMD runtime evidence: {exc}"]
    errors = validate(payload)
    return payload if isinstance(payload, dict) else None, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_file", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    args = parser.parse_args(argv)

    payload, errors = load_and_validate(args.evidence_file)
    if errors:
        if args.json:
            print(json.dumps({"ok": False, "errors": errors}, indent=2))
        else:
            for error in errors:
                print(f"ERROR: {error}")
        return 1

    assert payload is not None
    summary = {
        "ok": True,
        "capture_target": payload["capture_target"],
        "devices": [device["name"] for device in payload["devices"]],
        "rocm_version": payload["rocm_version"],
        "torch_version": payload["torch_version"],
        "vllm_version": payload["vllm_version"],
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            "AMD runtime evidence verified: "
            f"devices={','.join(summary['devices'])} "
            f"rocm={summary['rocm_version']} vllm={summary['vllm_version']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
