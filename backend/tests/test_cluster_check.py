"""Live-cluster readiness logic tested from a saved in-memory snapshot."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "check_cluster.py"
    spec = importlib.util.spec_from_file_location("check_cluster", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deployment(name: str):
    return {
        "kind": "Deployment",
        "metadata": {"name": name},
        "spec": {"replicas": 2},
        "status": {"readyReplicas": 2, "availableReplicas": 2},
    }


def _pod(name: str, node: str):
    return {
        "kind": "Pod",
        "metadata": {
            "name": f"{name}-{node}",
            "labels": {"app.kubernetes.io/name": name},
        },
        "spec": {"nodeName": node},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }


def test_cluster_snapshot_requires_multiple_ready_pods_and_pdbs():
    checker = _module()
    items = []
    for workload in checker.WORKLOADS:
        items.extend(
            [
                _deployment(workload),
                _pod(workload, "node-a"),
                _pod(workload, "node-b"),
                {"kind": "PodDisruptionBudget", "metadata": {"name": workload}},
            ]
        )
    errors, warnings = checker.evaluate_snapshot({"items": items})
    assert errors == []
    assert warnings == []


def test_cluster_snapshot_rejects_single_ready_replica():
    checker = _module()
    snapshot = {
        "items": [
            {
                "kind": "Deployment",
                "metadata": {"name": "hrcc-backend"},
                "spec": {"replicas": 1},
                "status": {"readyReplicas": 1, "availableReplicas": 1},
            },
            _pod("hrcc-backend", "node-a"),
        ]
    }
    errors, _ = checker.evaluate_snapshot(snapshot)
    assert any("desired replicas 1" in error for error in errors)
    assert any("fewer than two Ready pods" in error for error in errors)
