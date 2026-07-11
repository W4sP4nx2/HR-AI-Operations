"""Certify live pgvector and S3-compatible ETL integration state.

Run after Postgres/pgvector and MinIO/S3 are available. Credentials are read
from environment variables and never included in the output artifact.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from core.memory import memory
from scripts.generate_hackathon_datasets import DEFAULT_OUT
from scripts.load_poisoned_policies import load_and_probe
from scripts.upload_resume_dump import _common_prefix, _s3_list_objects, build_upload_plan


async def certify_integrations(
    *,
    corpus_dir: Path,
    resume_manifest: Path,
    endpoint: str,
    bucket: str,
    prefix: str,
    access_key: str,
    secret_key: str,
    region: str,
) -> dict[str, Any]:
    """Return sanitized evidence for the live pgvector and object-store gates."""
    policy_probe = await load_and_probe(corpus_dir, require_pgvector=True)
    pg_storage = await _pgvector_storage_evidence()
    plan = build_upload_plan(resume_manifest, bucket=bucket, prefix=prefix)
    listing = await asyncio.to_thread(
        _s3_list_objects,
        endpoint=endpoint,
        bucket=bucket,
        prefix=_common_prefix(plan),
        access_key=access_key,
        secret_key=secret_key,
        region=region,
    )
    minio_gate = _object_storage_gate(plan, listing, endpoint)
    pgvector_gate = _pgvector_gate(policy_probe, pg_storage)
    gates = [pgvector_gate, minio_gate]
    return {
        "certification": "live_etl_integrations",
        "captured_at": datetime.now(UTC).isoformat(),
        "ok": all(gate["ok"] for gate in gates),
        "gate_count": len(gates),
        "passed_count": sum(1 for gate in gates if gate["ok"]),
        "gates": gates,
    }


async def _pgvector_storage_evidence() -> dict[str, Any]:
    """Query extension, row-count, and temporal metadata evidence from Postgres."""
    async with memory.engine.connect() as conn:
        extension_version = (
            await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        ).scalar_one_or_none()
        synthetic_count = (
            await conn.execute(
                text("SELECT COUNT(*) FROM policy_chunks WHERE policy_id LIKE 'policy_%'")
            )
        ).scalar_one()
        pto_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT policy_id, metadata FROM policy_chunks "
                        "WHERE policy_id IN ('policy_pto_2023', 'policy_pto_2024') "
                        "ORDER BY policy_id"
                    )
                )
            )
            .mappings()
            .all()
        )
    pto_metadata = {row["policy_id"]: _decode_metadata(row["metadata"]) for row in pto_rows}
    return {
        "pgvector_extension_version": extension_version,
        "synthetic_policy_chunks": int(synthetic_count),
        "pto_metadata": pto_metadata,
    }


def _decode_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else {}


def _pgvector_gate(policy_probe: dict[str, Any], storage: dict[str, Any]) -> dict[str, Any]:
    pto = storage.get("pto_metadata", {})
    old = pto.get("policy_pto_2023", {})
    active = pto.get("policy_pto_2024", {})
    ok = (
        policy_probe.get("backend") == "pgvector"
        and policy_probe.get("passes_pto_trap") is True
        and policy_probe.get("winning_doc_id") == "policy_pto_2024"
        and bool(storage.get("pgvector_extension_version"))
        and int(storage.get("synthetic_policy_chunks", 0)) >= 40
        and old.get("status") == "expired"
        and active.get("status") == "active"
        and active.get("effective_date") == "2024-01-01"
    )
    return {
        "name": "postgres_pgvector_poisoned_policy",
        "ok": ok,
        "evidence": {
            "backend": policy_probe.get("backend"),
            "pgvector_extension_version": storage.get("pgvector_extension_version"),
            "chunks_loaded": policy_probe.get("chunks_loaded"),
            "stored_synthetic_policy_chunks": storage.get("synthetic_policy_chunks"),
            "winning_doc_id": policy_probe.get("winning_doc_id"),
            "passes_pto_trap": policy_probe.get("passes_pto_trap"),
            "pto_2023_status": old.get("status"),
            "pto_2023_expires_on": old.get("expires_on"),
            "pto_2024_status": active.get("status"),
            "pto_2024_effective_date": active.get("effective_date"),
        },
    }


def _object_storage_gate(
    plan: list[dict[str, Any]], listing: dict[str, Any], endpoint: str
) -> dict[str, Any]:
    expected = {row["key"] for row in plan}
    actual = set(listing["keys"])
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    parsed = urlparse(endpoint)
    ok = len(expected) == 1_000 and not missing and not unexpected
    return {
        "name": "minio_s3_resume_objects",
        "ok": ok,
        "evidence": {
            "endpoint_origin": f"{parsed.scheme}://{parsed.netloc}",
            "bucket": plan[0]["bucket"] if plan else None,
            "expected_objects": len(expected),
            "listed_objects": len(actual),
            "missing_count": len(missing),
            "unexpected_count": len(unexpected),
            "total_bytes": int(listing["total_bytes"]),
            "first_object_uri": plan[0]["uri"] if plan else None,
        },
    }


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_OUT / "poisoned_policies")
    parser.add_argument(
        "--resume-manifest",
        type=Path,
        default=DEFAULT_OUT / "resume_pdf_dump" / "resume_manifest.csv",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    config = {
        "endpoint": os.environ.get("S3_ENDPOINT_URL", ""),
        "bucket": os.environ.get("S3_BUCKET", "hrcc-synthetic-resumes"),
        "prefix": os.environ.get("S3_PREFIX", ""),
        "access_key": os.environ.get("AWS_ACCESS_KEY_ID", ""),
        "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        "region": os.environ.get("AWS_REGION", "us-east-1"),
    }
    missing = [name for name in ("endpoint", "access_key", "secret_key") if not config[name]]
    if missing:
        raise SystemExit("missing integration configuration: " + ", ".join(missing))

    result = asyncio.run(
        certify_integrations(
            corpus_dir=args.corpus_dir,
            resume_manifest=args.resume_manifest,
            **config,
        )
    )
    payload = json.dumps(result, indent=2, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
