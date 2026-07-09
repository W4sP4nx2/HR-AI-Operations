"""Static cluster checks run on CPU-only CI without kubectl or a GPU."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_verifier():
    path = Path(__file__).resolve().parents[2] / "scripts" / "verify_platform_manifests.py"
    spec = importlib.util.spec_from_file_location("verify_platform_manifests", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_manifests_pass_static_safety_and_multi_pod_checks():
    verifier = _load_verifier()
    assert verifier.verify() == []
