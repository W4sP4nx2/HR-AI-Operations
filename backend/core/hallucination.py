"""Anti-hallucination runtime metrics derived from governance evidence."""

from __future__ import annotations

from typing import Any

from core.a2a_envelope import recent_envelopes


def hallucination_metrics_snapshot(
    *,
    audit_counts: dict[str, int],
    window: int = 100,
) -> dict[str, Any]:
    """Return dashboard-ready anti-hallucination metrics without raw payloads."""
    events = recent_envelopes(window)
    by_agent: dict[str, dict[str, int]] = {}
    citation_total = 0
    citation_complete = 0
    pii_incidents = 0

    for event in events:
        row = by_agent.setdefault(event.source_agent, {"total": 0, "failed": 0})
        row["total"] += 1
        if not event.certification.is_valid:
            row["failed"] += 1
        if event.certification.redaction_count:
            pii_incidents += 1

        if "source_policy_count" in event.metadata:
            citation_total += 1
            if int(event.metadata.get("source_policy_count") or 0) > 0:
                citation_complete += 1
        elif "source_documents_count" in event.metadata:
            citation_total += 1
            if int(event.metadata.get("source_documents_count") or 0) > 0:
                citation_complete += 1

    triage_total = int(audit_counts.get("triage", 0))
    overrides = int(audit_counts.get("triage_override", 0))
    rejected = int(audit_counts.get("human_rejected", 0))
    human_denominator = triage_total + overrides + rejected

    return {
        "window": len(events),
        "certification_failure_rate_by_agent": {
            agent: round(row["failed"] / row["total"], 4) if row["total"] else 0.0
            for agent, row in sorted(by_agent.items())
        },
        "certification_counts_by_agent": {
            agent: {"total": row["total"], "failed": row["failed"]}
            for agent, row in sorted(by_agent.items())
        },
        "human_override_rate": (
            round((overrides + rejected) / human_denominator, 4) if human_denominator else None
        ),
        "human_override_counts": {
            "triage": triage_total,
            "triage_override": overrides,
            "human_rejected": rejected,
        },
        "citation_completeness_score": (
            round(citation_complete / citation_total, 4) if citation_total else None
        ),
        "citation_counts": {
            "checked": citation_total,
            "complete": citation_complete,
        },
        "pii_leak_incidents": pii_incidents,
        "triple_lock": {
            "schema_enforcement": "ChatResponse/Pydantic structured output",
            "certification_enforcement": "FireworksOutputCertifier schema + PII + confidence",
            "rag_grounding_enforcement": "source_policy_ids/citations + confidence review",
        },
    }
