"""Static safety and multi-pod checks for the optional Kubernetes platform."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "deploy" / "k8s" / "base"


def _documents(directory: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        with path.open(encoding="utf-8") as handle:
            docs.extend(
                doc for doc in yaml.safe_load_all(handle) if isinstance(doc, dict)
            )
    return docs


def verify() -> list[str]:
    """Return human-readable violations; an empty list is a pass."""
    errors: list[str] = []
    docs = _documents(BASE)
    kinds: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        kinds.setdefault(str(doc.get("kind")), []).append(doc)

    deployments = kinds.get("Deployment", [])
    if {d["metadata"]["name"] for d in deployments} != {
        "hrcc-backend",
        "hrcc-frontend",
        "hrcc-gpu-inference",
    }:
        errors.append("expected backend, frontend, and gpu-inference Deployments")

    for deployment in deployments:
        name = deployment["metadata"]["name"]
        replicas = int(deployment.get("spec", {}).get("replicas", 0))
        if replicas < 2:
            errors.append(f"{name}: replicas must be >=2 for the HA base")
        pod_spec = deployment["spec"]["template"]["spec"]
        if pod_spec.get("automountServiceAccountToken") is not False:
            errors.append(f"{name}: service-account token must not be mounted")
        if not pod_spec.get("securityContext", {}).get("runAsNonRoot"):
            errors.append(f"{name}: pod must run as non-root")
        for container in pod_spec.get("containers", []):
            image = str(container.get("image", ""))
            if not image or image.endswith(":latest"):
                errors.append(f"{name}: image must have a non-latest tag")
            resources = container.get("resources", {})
            if not resources.get("requests") or not resources.get("limits"):
                errors.append(f"{name}: resource requests and limits are required")
            security = container.get("securityContext", {})
            if security.get("allowPrivilegeEscalation") is not False:
                errors.append(f"{name}: privilege escalation must be disabled")
            if security.get("readOnlyRootFilesystem") is not True:
                errors.append(f"{name}: root filesystem must be read-only")
            if security.get("capabilities", {}).get("drop") != ["ALL"]:
                errors.append(f"{name}: all Linux capabilities must be dropped")

    gpu = next(
        (
            item
            for item in deployments
            if item["metadata"]["name"] == "hrcc-gpu-inference"
        ),
        None,
    )
    if gpu:
        container = gpu["spec"]["template"]["spec"]["containers"][0]
        resources = container["resources"]
        if resources["requests"].get("amd.com/gpu") != "1":
            errors.append("gpu-inference: AMD GPU request must be explicit")
        if resources["limits"].get("amd.com/gpu") != "1":
            errors.append("gpu-inference: AMD GPU limit must be explicit")
        image = str(container.get("image", ""))
        if not image.startswith("rocm/vllm:") or "gfx94X" not in image:
            errors.append("gpu-inference: use a pinned AMD ROCm/vLLM gfx94X image")
        command = " ".join(str(part) for part in container.get("command", []))
        if "vllm.entrypoints.openai.api_server" not in command:
            errors.append(
                "gpu-inference: explicit OpenAI-compatible vLLM command missing"
            )

    compose_path = ROOT / "docker-compose.amd.yml"
    if not compose_path.exists():
        errors.append("missing AMD Docker Compose overlay")
    else:
        with compose_path.open(encoding="utf-8") as handle:
            compose = yaml.safe_load(handle)
        services = compose.get("services", {})
        amd_service = services.get("amd-vllm", {})
        if amd_service.get("platform") != "linux/amd64":
            errors.append("amd compose: linux/amd64 platform must be explicit")
        if not str(amd_service.get("image", "")).startswith(
            "${AMD_VLLM_IMAGE:-rocm/vllm:"
        ):
            errors.append(
                "amd compose: default image must come from AMD's rocm/vllm repository"
            )
        devices = amd_service.get("devices", [])
        if not any("/dev/kfd" in str(device) for device in devices):
            errors.append("amd compose: /dev/kfd device missing")
        if not any("/dev/dri" in str(device) for device in devices):
            errors.append("amd compose: /dev/dri device missing")
        backend_env = services.get("backend", {}).get("environment", {})
        if ":?" not in str(backend_env.get("AMD_VLLM_BASE_URL", "")):
            errors.append("amd compose: AMD_VLLM_BASE_URL must be injected")

    pdb_names = {
        item["metadata"]["name"] for item in kinds.get("PodDisruptionBudget", [])
    }
    for name in ("hrcc-backend", "hrcc-frontend", "hrcc-gpu-inference"):
        if name not in pdb_names:
            errors.append(f"{name}: PodDisruptionBudget missing")

    hpa_names = {
        item["metadata"]["name"] for item in kinds.get("HorizontalPodAutoscaler", [])
    }
    for name in ("hrcc-backend", "hrcc-frontend"):
        if name not in hpa_names:
            errors.append(f"{name}: HorizontalPodAutoscaler missing")

    policies = kinds.get("NetworkPolicy", [])
    if not any(
        item["metadata"]["name"] == "default-deny"
        and item.get("spec", {}).get("podSelector") == {}
        for item in policies
    ):
        errors.append("namespace default-deny NetworkPolicy missing")
    if not kinds.get("ResourceQuota"):
        errors.append("ResourceQuota missing")
    if not kinds.get("Role") or not kinds.get("RoleBinding"):
        errors.append("namespace RBAC Role/RoleBinding missing")

    for required in (
        ROOT / "deploy" / "gitops" / "application.yaml",
        ROOT / "deploy" / "gitops" / "project.yaml",
        ROOT / "deploy" / "k8s" / "tenants" / "tenant-template.yaml",
        ROOT / "deploy" / "observability" / "servicemonitor.yaml",
        ROOT / "deploy" / "observability" / "prometheus-rules.yaml",
    ):
        if not required.exists():
            errors.append(f"missing platform artifact: {required.relative_to(ROOT)}")

    return errors


def main() -> int:
    errors = verify()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "Platform manifests pass multi-pod, security, GPU, GitOps, and observability checks."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
