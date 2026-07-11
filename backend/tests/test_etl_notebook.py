"""Executable contract for the Jupyter ETL validation walkthrough."""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "hr_governance_etl_validation.ipynb"


def _load_notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def test_etl_notebook_executes_all_local_code_cells() -> None:
    """Run code cells sequentially with plain Python, matching kernel semantics."""
    notebook = _load_notebook()
    namespace: dict[str, object] = {"__name__": "__etl_notebook_test__"}
    executed = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code" or "external" in cell.get("metadata", {}).get("tags", []):
            continue
        source = "".join(cell["source"])
        exec(compile(source, f"{NOTEBOOK.name}:{cell['id']}", "exec"), namespace)
        executed.append(cell["id"])

    assert executed == [
        "setup",
        "extract-contracts",
        "temporal-policy",
        "bias-calculation",
        "local-certification",
    ]
    assert namespace["dataset_counts"]["ats_rows"] == 10_000
    assert namespace["certification"]["ok"] is True


def test_etl_notebook_external_loads_are_explicitly_gated() -> None:
    """Prevent pgvector/MinIO cells from silently becoming local-pass claims."""
    notebook = _load_notebook()
    external = next(cell for cell in notebook["cells"] if cell.get("id") == "external-integrations")
    source = "".join(external["source"])

    assert external["metadata"]["tags"] == ["external"]
    assert "HRCC_RUN_EXTERNAL_ETL" in source
    assert "--require-pgvector" in source
    assert "--upload" in source
    assert "live_gated" in source
