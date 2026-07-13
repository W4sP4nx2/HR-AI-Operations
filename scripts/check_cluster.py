"""Read-only live Kubernetes readiness check for the multi-pod platform."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from typing import Any

WORKLOADS = {"hrcc-backend", "hrcc-frontend", "hrcc-gpu-inference"}


def evaluate_snapshot(snapshot: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return errors and warnings from a kubectl List response."""
    errors: list[str] = []
    warnings: list[str] = []
    deployments: dict[str, dict[str, Any]] = {}
    ready_pods: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pdbs: dict[str, dict[str, Any]] = {}

    for item in snapshot.get("items", []):
        kind = item.get("kind")
        name = item.get("metadata", {}).get("name", "")
        if kind == "Deployment":
            deployments[name] = item
        elif kind == "Pod":
            labels = item.get("metadata", {}).get("labels", {})
            workload = labels.get("app.kubernetes.io/name", "")
            conditions = item.get("status", {}).get("conditions", [])
            ready = any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in conditions
            )
            if ready:
                ready_pods[workload].append(item)
        elif kind == "PodDisruptionBudget":
            pdbs[name] = item

    for workload in sorted(WORKLOADS):
        deployment = deployments.get(workload)
        if not deployment:
            errors.append(f"{workload}: Deployment not found")
            continue
        desired = int(deployment.get("spec", {}).get("replicas", 0))
        ready_replicas = int(deployment.get("status", {}).get("readyReplicas", 0))
        available = int(deployment.get("status", {}).get("availableReplicas", 0))
        if desired < 2:
            errors.append(
                f"{workload}: desired replicas {desired}, expected at least 2"
            )
        if ready_replicas < 2 or available < 2:
            errors.append(
                f"{workload}: ready={ready_replicas}, available={available}; expected >=2"
            )
        if len(ready_pods.get(workload, [])) < 2:
            errors.append(f"{workload}: fewer than two Ready pods")
        if workload not in pdbs:
            errors.append(f"{workload}: PodDisruptionBudget not found")

        nodes = {
            pod.get("spec", {}).get("nodeName")
            for pod in ready_pods.get(workload, [])
            if pod.get("spec", {}).get("nodeName")
        }
        if len(ready_pods.get(workload, [])) >= 2 and len(nodes) < 2:
            warnings.append(
                f"{workload}: Ready pods are not spread across multiple nodes"
            )

    return errors, warnings


def collect_snapshot(namespace: str) -> dict[str, Any]:
    """Collect only read-only workload state through kubectl."""
    command = [
        "kubectl",
        "get",
        "deployments,pods,pdb",
        "--namespace",
        namespace,
        "--output",
        "json",
    ]
    completed = subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=30
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="hr-ai-system")
    parser.add_argument(
        "--snapshot", help="evaluate saved kubectl JSON instead of a live cluster"
    )
    args = parser.parse_args()
    if args.snapshot:
        with open(args.snapshot, encoding="utf-8") as handle:
            snapshot = json.load(handle)
    else:
        try:
            snapshot = collect_snapshot(args.namespace)
        except (
            FileNotFoundError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
        ) as exc:
            print(f"Cluster check unavailable: {exc}", file=sys.stderr)
            return 2

    errors, warnings = evaluate_snapshot(snapshot)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(
        "All backend, frontend, and GPU inference workloads have at least two Ready pods."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
