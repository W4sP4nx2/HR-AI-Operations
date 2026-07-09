"""Small AMD GPU status probe for lifecycle evidence."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any


def gpu_status_snapshot(timeout_seconds: float = 2.0) -> dict[str, Any]:
    """Return a bounded, secret-free ROCm status snapshot."""
    if shutil.which("rocm-smi") is None:
        return {
            "available": False,
            "provider": "rocm-smi",
            "reason": "rocm-smi not found",
        }
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "--showuse", "--showmemuse"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "provider": "rocm-smi",
            "reason": "rocm-smi timed out",
        }
    return {
        "available": result.returncode == 0,
        "provider": "rocm-smi",
        "returncode": result.returncode,
        "output": result.stdout[-4000:],
        "error": result.stderr[-1000:],
    }
