"""Static safety and multi-pod checks for the optional Kubernetes platform."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "deploy" / "k8s" / "base"
# Verified against AMD's official rocm/vllm Docker Hub entry on 2026-07-10.
AMD_VLLM_IMAGE = (
    "rocm/vllm:rocm7.13.0_gfx94X-dcgpu_ubuntu24.04_py3.13_"
    "pytorch_2.10.0_vllm_0.19.1@sha256:"
    "75503c82b8a1d3c970b19d1ac1a3e3c96436aab6d3695580527f8581694f3b2d"
)


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
        if image != AMD_VLLM_IMAGE:
            errors.append(
                "gpu-inference: use the reviewed AMD ROCm/vLLM gfx94X image and digest"
            )
        command = " ".join(str(part) for part in container.get("command", []))
        if "vllm.entrypoints.openai.api_server" not in command:
            errors.append(
                "gpu-inference: explicit OpenAI-compatible vLLM command missing"
            )
        env_by_name = {
            str(item.get("name")): item
            for item in container.get("env", [])
            if isinstance(item, dict)
        }
        for env_name in ("MODEL_ID", "SERVED_MODEL_NAME"):
            secret_name = (
                env_by_name.get(env_name, {})
                .get("valueFrom", {})
                .get("secretKeyRef", {})
                .get("name")
            )
            if secret_name != "hrcc-gpu-secrets":
                errors.append(f"gpu-inference: {env_name} must use the GPU-only secret")
        api_secret_name = (
            env_by_name.get("VLLM_API_KEY", {})
            .get("valueFrom", {})
            .get("secretKeyRef", {})
            .get("name")
        )
        if api_secret_name != "hrcc-secrets":
            errors.append("gpu-inference: shared vLLM API key must use the backend secret")
        args = " ".join(str(part) for part in container.get("args", []))
        if "--api-key" in args:
            errors.append("gpu-inference: vLLM API key must not appear in process arguments")

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
        expected_compose_image = f"${{AMD_VLLM_IMAGE:-{AMD_VLLM_IMAGE}}}"
        if str(amd_service.get("image", "")) != expected_compose_image:
            errors.append(
                "amd compose: default AMD image must include the reviewed immutable digest"
            )
        devices = amd_service.get("devices", [])
        if not any("/dev/kfd" in str(device) for device in devices):
            errors.append("amd compose: /dev/kfd device missing")
        if not any("/dev/dri" in str(device) for device in devices):
            errors.append("amd compose: /dev/dri device missing")
        backend_env = services.get("backend", {}).get("environment", {})
        if ":?" not in str(backend_env.get("AMD_VLLM_BASE_URL", "")):
            errors.append("amd compose: AMD_VLLM_BASE_URL must be injected")
        for name in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "POSTGRES_PASSWORD"):
            value = (
                backend_env.get(name, "")
                if name != "POSTGRES_PASSWORD"
                else backend_env.get("DATABASE_URL", "")
            )
            if ":?" not in str(value):
                errors.append(f"amd compose: {name} must be required for the judged profile")
        if str(backend_env.get("AUTH_OPEN_REGISTRATION", "")).lower() != "false":
            errors.append("amd compose: public registration must be disabled")
        amd_env = amd_service.get("environment", {})
        if ":?" not in str(amd_env.get("HF_TOKEN", "")):
            errors.append("amd compose: HF_TOKEN must be required for gated Gemma weights")
        if ":?" not in str(amd_env.get("VLLM_API_KEY", "")):
            errors.append("amd compose: VLLM_API_KEY must be required")
        compose_command = " ".join(str(part) for part in amd_service.get("command", []))
        if "--max-model-len" not in compose_command:
            errors.append("amd compose: bounded Gemma context length is required")
        if "--api-key" in compose_command:
            errors.append("amd compose: vLLM API key must not appear in process arguments")
        if amd_service.get("ipc") == "host":
            errors.append("amd compose: do not share the host IPC namespace")
        if not any(
            str(port).startswith("${AMD_VLLM_BIND:-127.0.0.1}:")
            for port in amd_service.get("ports", [])
        ):
            errors.append("amd compose: direct vLLM port must bind to loopback by default")

        with (ROOT / "docker-compose.prod.yml").open(encoding="utf-8") as handle:
            production_compose = yaml.safe_load(handle)
        production_services = production_compose.get("services", {})
        db_ports = production_services.get("db", {}).get("ports", [])
        if "127.0.0.1:5432:5432" not in [str(port) for port in db_ports]:
            errors.append("production compose: PostgreSQL port must bind to loopback")
        production_backend_env = production_services.get("backend", {}).get(
            "environment", {}
        )
        if production_backend_env.get("AUTH_OPEN_REGISTRATION") != (
            "${AUTH_OPEN_REGISTRATION:-false}"
        ):
            errors.append("production compose: public registration must default to disabled")

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
