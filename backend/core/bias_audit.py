"""Deterministic adverse-impact auditing for synthetic hiring datasets.

This module intentionally avoids pandas/numpy so the audit can run in the lean
runtime image. It computes selection rates and Four-Fifths rule ratios from a
CSV containing protected-group columns plus a binary decision column.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FOUR_FIFTHS_THRESHOLD = 0.80
DEFAULT_SYNTHETIC_ATS_PATH = (
    Path(__file__).resolve().parents[1]
    / "sample_data"
    / "hackathon"
    / "adverse_impact_ats"
    / "synthetic_ats_hiring_data.csv"
)


@dataclass(frozen=True)
class GroupRate:
    """Selection-rate evidence for one demographic group."""

    group: str
    selected: int
    total: int
    selection_rate: float

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "group": self.group,
            "selected": self.selected,
            "total": self.total,
            "selection_rate": self.selection_rate,
        }


@dataclass(frozen=True)
class DimensionAudit:
    """Four-Fifths audit result for one protected dimension."""

    dimension: str
    reference_group: str
    reference_rate: float
    lowest_group: str
    lowest_rate: float
    adverse_impact_ratio: float
    threshold: float
    violates_four_fifths_rule: bool
    groups: list[GroupRate]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "dimension": self.dimension,
            "reference_group": self.reference_group,
            "reference_rate": self.reference_rate,
            "lowest_group": self.lowest_group,
            "lowest_rate": self.lowest_rate,
            "adverse_impact_ratio": self.adverse_impact_ratio,
            "threshold": self.threshold,
            "violates_four_fifths_rule": self.violates_four_fifths_rule,
            "groups": [group.as_dict() for group in self.groups],
        }


def audit_hiring_csv(
    path: str | Path = DEFAULT_SYNTHETIC_ATS_PATH,
    *,
    dimensions: tuple[str, ...] = ("gender", "race", "age_group"),
    decision_column: str = "hired",
    threshold: float = FOUR_FIFTHS_THRESHOLD,
) -> dict[str, Any]:
    """Audit a hiring CSV for Four-Fifths rule violations.

    The reference group is the group with the highest selection rate in that
    dimension. The reported ratio is lowest-rate / reference-rate. This makes a
    deliberately biased race fixture surface as roughly 0.71.
    """
    csv_path = Path(path)
    rows = _read_rows(csv_path)
    audits = [
        _audit_dimension(
            rows,
            dimension=dimension,
            decision_column=decision_column,
            threshold=threshold,
        )
        for dimension in dimensions
    ]
    violations = [audit for audit in audits if audit.violates_four_fifths_rule]
    return {
        "dataset_path": str(csv_path),
        "record_count": len(rows),
        "decision_column": decision_column,
        "threshold": threshold,
        "violations_count": len(violations),
        "violates_four_fifths_rule": bool(violations),
        "dimensions": [audit.as_dict() for audit in audits],
        "headline": _headline(violations),
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"synthetic ATS dataset not found at {path}; run "
            "`python -m scripts.generate_hackathon_datasets` first"
        )
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"synthetic ATS dataset is empty: {path}")
    return rows


def _audit_dimension(
    rows: list[dict[str, str]],
    *,
    dimension: str,
    decision_column: str,
    threshold: float,
) -> DimensionAudit:
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        if dimension not in row:
            raise KeyError(f"missing protected dimension column: {dimension}")
        if decision_column not in row:
            raise KeyError(f"missing decision column: {decision_column}")
        group = row[dimension]
        bucket = counts.setdefault(group, {"selected": 0, "total": 0})
        bucket["total"] += 1
        bucket["selected"] += 1 if _truthy(row[decision_column]) else 0

    groups = [
        GroupRate(
            group=group,
            selected=values["selected"],
            total=values["total"],
            selection_rate=(
                round(values["selected"] / values["total"], 4) if values["total"] else 0.0
            ),
        )
        for group, values in sorted(counts.items())
    ]
    reference = max(groups, key=lambda item: item.selection_rate)
    lowest = min(groups, key=lambda item: item.selection_rate)
    ratio = (
        round(lowest.selection_rate / reference.selection_rate, 4)
        if reference.selection_rate
        else 0.0
    )
    return DimensionAudit(
        dimension=dimension,
        reference_group=reference.group,
        reference_rate=reference.selection_rate,
        lowest_group=lowest.group,
        lowest_rate=lowest.selection_rate,
        adverse_impact_ratio=ratio,
        threshold=threshold,
        violates_four_fifths_rule=ratio < threshold,
        groups=groups,
    )


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "selected", "hired"}


def _headline(violations: list[DimensionAudit]) -> str:
    if not violations:
        return "No Four-Fifths rule violations detected."
    worst = min(violations, key=lambda item: item.adverse_impact_ratio)
    return (
        f"{worst.dimension} adverse-impact alert: {worst.lowest_group} selection "
        f"ratio {worst.adverse_impact_ratio:.2f} is below {worst.threshold:.2f}."
    )
