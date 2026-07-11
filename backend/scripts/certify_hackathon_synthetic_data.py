"""Certify the synthetic hackathon datasets and their guardrail traps.

This is a no-network evidence command for the demo:

    python -m scripts.certify_hackathon_synthetic_data

It verifies:
  * poisoned PTO policy conflicts resolve to the active 2024 source,
  * the synthetic ATS dump trips the Four-Fifths rule,
  * SSNs are redacted before audit/provider exposure,
  * prompt injection is detected,
  * the resume PDF batch manifest contains the expected volume.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from core.bias_audit import audit_hiring_csv
from core.config import settings
from core.guardrails import detect_prompt_injection
from core.safety import redact_pii
from pipelines.ingestion import ingest_pdf
from scripts.generate_hackathon_datasets import DEFAULT_OUT, generate_all
from scripts.upload_resume_dump import build_upload_plan
from services.rag import _apply_active_policy_version_filter


def certify(out_dir: Path = DEFAULT_OUT, *, ensure_generated: bool = True) -> dict[str, Any]:
    """Return certification evidence for the synthetic governance bundle."""
    if ensure_generated and not (out_dir / "README.generated.json").exists():
        generate_all(
            out_dir,
            ats_records=10_000,
            guardrail_questions=500,
            resumes=1_000,
            seed=42,
        )

    policy_gate = _certify_policy_versioning(out_dir)
    bias_gate = _certify_bias_audit(out_dir)
    guardrail_gate = _certify_pii_and_injection(out_dir)
    resume_gate = _certify_resume_batch(out_dir)
    storage_gate = _certify_object_storage_plan(out_dir)
    gates = [policy_gate, bias_gate, guardrail_gate, resume_gate, storage_gate]
    return {
        "certification": "hackathon_synthetic_data",
        "ok": all(gate["ok"] for gate in gates),
        "gate_count": len(gates),
        "passed_count": sum(1 for gate in gates if gate["ok"]),
        "gates": gates,
    }


def _certify_policy_versioning(out_dir: Path) -> dict[str, Any]:
    manifest = out_dir / "poisoned_policies" / "synthetic_policy_manifest.csv"
    rows = _read_csv(manifest)
    pto_active = next(row for row in rows if row["doc_id"] == "policy_pto_2024")
    pto_expired = next(row for row in rows if row["doc_id"] == "policy_pto_2023")
    static_hits = _apply_active_policy_version_filter(
        [
            {
                "doc_id": "policy_pto_2023",
                "score": 0.99,
                "text": "Employees get 15 days PTO.",
                "metadata": {
                    "policy_family": "policy_pto",
                    "effective_date": pto_expired["effective_date"],
                    "expires_on": pto_expired["expires_on"],
                    "status": pto_expired["status"],
                },
            },
            {
                "doc_id": "policy_pto_2024",
                "score": 0.91,
                "text": pto_active["expected_active_fact"],
                "metadata": {
                    "policy_family": "policy_pto",
                    "effective_date": pto_active["effective_date"],
                    "expires_on": pto_active["expires_on"],
                    "status": pto_active["status"],
                },
            },
        ]
    )
    rag_evidence = asyncio.run(_rag_policy_versioning_evidence(out_dir))
    ok = (
        static_hits[0]["doc_id"] == "policy_pto_2024"
        and "25 days PTO" in static_hits[0]["text"]
        and rag_evidence["winning_doc_id"] == "policy_pto_2024"
        and rag_evidence["mentions_25_days"] is True
        and rag_evidence["mentions_15_days"] is False
    )
    return {
        "name": "poisoned_policy_versioning",
        "ok": ok,
        "detail": "Active 2024 PTO policy wins over expired 2023 policy in RAG retrieval.",
        "evidence": {
            "query": pto_active["expected_query"],
            "selection_basis": "effective_date/status metadata",
            "static_filter_winning_doc_id": static_hits[0]["doc_id"] if static_hits else None,
            "winning_doc_id": rag_evidence["winning_doc_id"],
            "required_doc_id": "policy_pto_2024",
            "answer_excerpt": rag_evidence["answer_excerpt"],
            "ingested_chunks": rag_evidence["ingested_chunks"],
        },
    }


async def _rag_policy_versioning_evidence(out_dir: Path) -> dict[str, Any]:
    """Ingest the poisoned PTO PDFs into an isolated local RAG store and query it."""
    import core.memory as memmod
    from core.memory import Memory
    from services import local_vector_store, rag

    saved_memory = memmod.memory
    saved_ready = local_vector_store.local_vector_store._ready
    saved_mock_llm = settings.mock_llm
    saved_embedding_provider = os.environ.get("EMBEDDING_PROVIDER")
    chunks = []
    try:
        with tempfile.TemporaryDirectory(prefix="hrcc_poisoned_rag_") as tmp:
            memmod.memory = Memory(f"sqlite:///{Path(tmp) / 'rag.db'}")
            local_vector_store.local_vector_store._ready = False
            settings.mock_llm = True
            os.environ["EMBEDDING_PROVIDER"] = "hashing"
            for version in ("2023", "2024"):
                path = out_dir / "poisoned_policies" / f"policy_pto_{version}.pdf"
                chunks.extend(ingest_pdf(str(path), doc_id=f"policy_pto_{version}"))
            written = await rag.ingest_chunks(chunks)
            result = await rag.query("How many PTO days do I have?", top_k=5)
            source_documents = result.get("source_documents", [])
            answer = str(result.get("answer", ""))
            return {
                "ingested_chunks": written,
                "winning_doc_id": source_documents[0]["doc_id"] if source_documents else None,
                "source_doc_ids": [doc.get("doc_id") for doc in source_documents],
                "mentions_25_days": "25 days PTO" in answer,
                "mentions_15_days": "15 days PTO" in answer,
                "answer_excerpt": answer[:220],
            }
    finally:
        await memmod.memory.engine.dispose()
        memmod.memory = saved_memory
        local_vector_store.local_vector_store._ready = saved_ready
        settings.mock_llm = saved_mock_llm
        if saved_embedding_provider is None:
            os.environ.pop("EMBEDDING_PROVIDER", None)
        else:
            os.environ["EMBEDDING_PROVIDER"] = saved_embedding_provider


def _certify_bias_audit(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "adverse_impact_ats" / "synthetic_ats_hiring_data.csv"
    audit = audit_hiring_csv(path)
    race = next(item for item in audit["dimensions"] if item["dimension"] == "race")
    ok = bool(audit["violates_four_fifths_rule"]) and race["adverse_impact_ratio"] < 0.80
    return {
        "name": "four_fifths_bias_audit",
        "ok": ok,
        "detail": audit["headline"],
        "evidence": {
            "record_count": audit["record_count"],
            "race_ratio": race["adverse_impact_ratio"],
            "threshold": audit["threshold"],
            "lowest_group": race["lowest_group"],
        },
    }


def _certify_pii_and_injection(out_dir: Path) -> dict[str, Any]:
    rows = _read_csv(out_dir / "pii_injection_stress" / "synthetic_hr_guardrail_questions.csv")
    ssn_query = next(row["query"] for row in rows if row["scenario"] == "ssn")
    injection_queries = [row["query"] for row in rows if row["scenario"] == "jailbreak"]
    redacted = redact_pii(ssn_query)
    injection_results = [detect_prompt_injection(query) for query in injection_queries]
    raw_ssn = re.search(r"\b\d{3}-\d{2}-\d{4}\b", ssn_query)
    ok = (
        raw_ssn is not None
        and raw_ssn.group(0) not in redacted
        and "[redacted-ssn]" in redacted
        and bool(injection_results)
        and all(injection_results)
    )
    return {
        "name": "pii_redaction_and_injection_block",
        "ok": ok,
        "detail": "SSN is redacted and jailbreak text is blocked before model execution.",
        "evidence": {
            "redacted_example": redacted,
            "jailbreak_rows": len(injection_queries),
            "jailbreak_rows_blocked": sum(1 for blocked in injection_results if blocked),
        },
    }


def _certify_resume_batch(out_dir: Path) -> dict[str, Any]:
    manifest = out_dir / "resume_pdf_dump" / "resume_manifest.csv"
    batch_manifest = out_dir / "resume_pdf_dump" / "fireworks_resume_vision_batch_manifest.jsonl"
    rows = _read_csv(manifest)
    batch_lines = [line for line in batch_manifest.read_text(encoding="utf-8").splitlines() if line]
    ok = len(rows) == 1_000 and len(batch_lines) == 1_000
    return {
        "name": "resume_pdf_batch_manifest",
        "ok": ok,
        "detail": "Synthetic resume PDFs and Fireworks-style batch rows are present.",
        "evidence": {
            "resume_rows": len(rows),
            "batch_rows": len(batch_lines),
            "first_batch_row": json.loads(batch_lines[0]) if batch_lines else None,
        },
    }


def _certify_object_storage_plan(out_dir: Path) -> dict[str, Any]:
    manifest = out_dir / "resume_pdf_dump" / "resume_manifest.csv"
    plan = build_upload_plan(manifest)
    ok = len(plan) == 1_000 and all(row["uri"].startswith("s3://") for row in plan)
    return {
        "name": "resume_object_storage_plan",
        "ok": ok,
        "detail": "Synthetic resume PDFs have deterministic MinIO/S3 object keys.",
        "evidence": {
            "planned_uploads": len(plan),
            "bucket": plan[0]["bucket"] if plan else None,
            "first_uri": plan[0]["uri"] if plan else None,
            "first_sha256": plan[0]["sha256"] if plan else None,
        },
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="Fail if data is missing instead of generating the default bundle.",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional JSON evidence output path."
    )
    args = parser.parse_args()
    result = certify(args.out_dir, ensure_generated=not args.no_generate)
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
