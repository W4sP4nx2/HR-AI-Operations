"""Verify SHA-256 integrity for a generated hackathon evidence bundle.

Usage:
  python scripts/verify_evidence_manifest.py hackathon-evidence/<timestamp>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

MANIFEST_NAME = "EVIDENCE_MANIFEST.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_manifest(evidence_dir: Path) -> dict[str, Any]:
    manifest_path = evidence_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise ValueError(f"missing {MANIFEST_NAME}")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{MANIFEST_NAME} is not a JSON object")
    return value


def verify(evidence_dir: Path) -> list[str]:
    """Return integrity errors for an evidence bundle."""
    errors: list[str] = []
    if not evidence_dir.is_dir():
        return [f"evidence directory not found: {evidence_dir}"]
    try:
        manifest = _load_manifest(evidence_dir)
    except Exception as exc:  # noqa: BLE001 - operator-facing verifier
        return [str(exc)]

    rows = manifest.get("files")
    if not isinstance(rows, list):
        return [f"{MANIFEST_NAME} missing files list"]

    expected_paths: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            errors.append("manifest file row is not an object")
            continue
        rel_path = str(row.get("path") or "")
        if not rel_path or rel_path == MANIFEST_NAME or "/" in rel_path or "\\" in rel_path:
            errors.append(f"invalid manifest path: {rel_path!r}")
            continue
        if rel_path in expected_paths:
            errors.append(f"duplicate manifest path: {rel_path}")
            continue
        expected_paths.add(rel_path)
        path = evidence_dir / rel_path
        if path.is_symlink():
            errors.append(f"symbolic links are not allowed: {rel_path}")
            continue
        if not path.is_file():
            errors.append(f"missing evidence file: {rel_path}")
            continue
        data = path.read_bytes()
        expected_size = row.get("bytes")
        expected_hash = row.get("sha256")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool):
            errors.append(f"invalid byte size for {rel_path}")
            continue
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            errors.append(f"invalid sha256 for {rel_path}")
            continue
        if expected_size != len(data):
            errors.append(
                f"size mismatch for {rel_path}: expected {expected_size}, got {len(data)}"
            )
        actual_hash = hashlib.sha256(data).hexdigest()
        if expected_hash != actual_hash:
            errors.append(f"sha256 mismatch for {rel_path}")

    unexpected_dirs = sorted(path.name for path in evidence_dir.iterdir() if path.is_dir())
    if unexpected_dirs:
        errors.append("unexpected directories in evidence bundle: " + ", ".join(unexpected_dirs))

    actual_paths = {
        path.name
        for path in evidence_dir.iterdir()
        if path.is_file() and path.name != MANIFEST_NAME
    }
    extra_paths = sorted(actual_paths - expected_paths)
    if extra_paths:
        errors.append("files missing from manifest: " + ", ".join(extra_paths))

    expected_count = manifest.get("file_count")
    if not isinstance(expected_count, int) or isinstance(expected_count, bool):
        errors.append("file_count must be an integer")
        return errors
    if expected_count != len(expected_paths):
        errors.append(f"file_count mismatch: expected {expected_count}, got {len(expected_paths)}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir", type=Path)
    args = parser.parse_args(argv)

    errors = verify(args.evidence_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Evidence manifest verified for {args.evidence_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
