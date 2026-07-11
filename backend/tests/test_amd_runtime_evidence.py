"""No-network tests for AMD runtime capture and validation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts" / "verify_amd_runtime_evidence.py"
CAPTURE_PATH = ROOT / "scripts" / "capture_amd_runtime_evidence.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load("verify_amd_runtime_evidence", VERIFIER_PATH)
capture = _load("capture_amd_runtime_evidence", CAPTURE_PATH)


def _valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "captured_at": "2026-07-10T10:00:00+00:00",
        "capture_target": "kubernetes",
        "python_version": "3.13.5",
        "torch_version": "2.10.0+rocm7.1",
        "rocm_version": "7.1",
        "vllm_version": "0.19.1",
        "torch_cuda_available": True,
        "device_count": 1,
        "devices": [
            {
                "index": 0,
                "name": "AMD Instinct MI300X",
                "total_memory_bytes": 201_433_862_144,
            }
        ],
    }


def test_verifier_accepts_named_amd_rocm_runtime() -> None:
    assert verifier.validate(_valid_payload()) == []


def test_verifier_rejects_manifest_only_claim() -> None:
    errors = verifier.validate(
        {
            "schema_version": 1,
            "captured_at": "2026-07-10T10:00:00+00:00",
            "capture_target": "kubernetes",
            "device_count": 0,
            "devices": [],
        }
    )

    assert "rocm_version is missing" in errors
    assert "vllm_version is missing" in errors
    assert "device_count must be a positive integer" in errors


def test_verifier_rejects_non_amd_device_identity() -> None:
    payload = _valid_payload()
    devices = payload["devices"]
    assert isinstance(devices, list)
    devices[0]["name"] = "NVIDIA A100-SXM4-80GB"

    errors = verifier.validate(payload)

    assert "devices[0].name does not identify AMD hardware" in errors


def test_capture_adds_provenance_and_validates(monkeypatch) -> None:
    runtime = {
        key: value
        for key, value in _valid_payload().items()
        if key not in {"schema_version", "captured_at", "capture_target"}
    }
    monkeypatch.setattr(
        capture.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(runtime),
            stderr="",
        ),
    )

    payload = capture.capture("local")

    assert payload["capture_target"] == "local"
    assert payload["devices"] == runtime["devices"]


def test_kubernetes_command_targets_inference_container() -> None:
    command = capture.probe_command(
        "kubernetes",
        namespace="hr-ai-system",
        deployment="hrcc-gpu-inference",
        container="inference",
    )

    assert command[:4] == ["kubectl", "-n", "hr-ai-system", "exec"]
    assert "deploy/hrcc-gpu-inference" in command
    assert "inference" in command
