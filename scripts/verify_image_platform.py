"""Verify that a pushed Docker image exposes the required platform.

Usage:
  docker buildx imagetools inspect IMAGE --format "{{json .}}" \
    | python scripts/verify_image_platform.py --platform linux/amd64

Or let the script call Docker:
  python scripts/verify_image_platform.py IMAGE --platform linux/amd64
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def _load_payload(image: str | None) -> dict[str, Any]:
    if image:
        result = subprocess.run(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                image,
                "--format",
                "{{json .}}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        raw = result.stdout
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError(
            "provide an image reference or pipe Docker buildx imagetools JSON on stdin"
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Docker image inspection did not return valid JSON") from exc


def _platforms(payload: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    candidates = [payload]
    for key in ("Manifest", "Image"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)

    for candidate in candidates:
        for manifest in candidate.get("manifests", []):
            platform = manifest.get("platform", {})
            os_name = platform.get("os")
            arch = platform.get("architecture")
            variant = platform.get("variant")
            if os_name and arch:
                suffix = f"/{variant}" if variant else ""
                found.add(f"{os_name}/{arch}{suffix}")

        os_name = candidate.get("os")
        arch = candidate.get("architecture")
        variant = candidate.get("variant")
        if os_name and arch:
            suffix = f"/{variant}" if variant else ""
            found.add(f"{os_name}/{arch}{suffix}")

    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?")
    parser.add_argument("--platform", default="linux/amd64")
    args = parser.parse_args()

    try:
        payload = _load_payload(args.image)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"image platform verification failed: {exc}", file=sys.stderr)
        return 2

    platforms = _platforms(payload)
    if args.platform not in platforms:
        print(
            f"missing required platform {args.platform}; found: {', '.join(sorted(platforms)) or 'none'}",
            file=sys.stderr,
        )
        return 1
    print(f"ok: found {args.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
