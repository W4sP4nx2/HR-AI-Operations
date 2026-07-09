"""Unit tests for the Docker image platform verifier helper."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "verify_image_platform.py"

spec = importlib.util.spec_from_file_location("verify_image_platform", SCRIPT)
assert spec and spec.loader
verify_image_platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_image_platform)


def test_manifest_list_platform_detection() -> None:
    payload = {
        "Manifest": {
            "manifests": [
                {"platform": {"os": "linux", "architecture": "arm64"}},
                {"platform": {"os": "linux", "architecture": "amd64"}},
            ]
        }
    }

    assert "linux/amd64" in verify_image_platform._platforms(payload)


def test_single_image_platform_detection() -> None:
    payload = {"Image": {"os": "linux", "architecture": "amd64"}}

    assert verify_image_platform._platforms(payload) == {"linux/amd64"}


def test_missing_image_or_stdin_returns_actionable_error() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "provide an image reference" in result.stderr
