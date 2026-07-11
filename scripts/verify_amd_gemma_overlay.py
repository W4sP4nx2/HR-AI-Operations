"""Static verifier for the AMD-hosted Gemma Kubernetes overlay.

The check is intentionally offline: it validates that the repository contains a
deployable profile for the judged AMD/Gemma path and that the example secret
contract is self-consistent. Live GPU availability and model serving still need
cluster evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "deploy" / "k8s" / "overlays" / "amd-gemma"
BASE_GPU = ROOT / "deploy" / "k8s" / "base" / "gpu-inference.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} is not a YAML mapping")
    return value


def _read_first_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = next(yaml.safe_load_all(handle), None)
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} has no YAML mapping")
    return value


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid env line in {path.relative_to(ROOT)}: {raw_line!r}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _contains_gemma(value: str) -> bool:
    lowered = value.lower()
    return "gemma" in lowered or "gamma" in lowered


def verify() -> list[str]:
    errors: list[str] = []
    required = [
        OVERLAY / "kustomization.yaml",
        OVERLAY / "patch-configmap.yaml",
        OVERLAY / "patch-gpu-inference.yaml",
        OVERLAY / "patch-model-cache.yaml",
        OVERLAY / "model-download-egress.yaml",
        OVERLAY / "backend-database-egress.yaml",
        OVERLAY / "hrcc-secrets.example.env",
        OVERLAY / "hrcc-gpu-secrets.example.env",
        OVERLAY / "README.md",
        BASE_GPU,
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing {path.relative_to(ROOT)}")
    if errors:
        return errors

    kustomization = _read_yaml(OVERLAY / "kustomization.yaml")
    resources = kustomization.get("resources", [])
    if "../../base" not in resources:
        errors.append("amd-gemma overlay must reference ../../base")
    if "model-download-egress.yaml" not in resources:
        errors.append("amd-gemma overlay must include controlled HTTPS model download egress")
    if "backend-database-egress.yaml" not in resources:
        errors.append("amd-gemma overlay must include PostgreSQL egress for the backend")
    patches = {
        item.get("path") for item in kustomization.get("patches", []) if isinstance(item, dict)
    }
    for patch in (
        "patch-configmap.yaml",
        "patch-gpu-inference.yaml",
        "patch-model-cache.yaml",
    ):
        if patch not in patches:
            errors.append(f"amd-gemma overlay missing patch {patch}")
    label_entries = kustomization.get("labels", [])
    labels: dict[str, str] = {}
    selectors_included = False
    for entry in label_entries if isinstance(label_entries, list) else []:
        if not isinstance(entry, dict):
            continue
        pairs = entry.get("pairs", {})
        if isinstance(pairs, dict):
            labels.update({str(key): str(value) for key, value in pairs.items()})
        if entry.get("includeSelectors") is True:
            selectors_included = True
    if labels.get("hackathon.hrcc.ai/track") != "best-amd-hosted-gemma":
        errors.append("amd-gemma overlay must carry the hackathon track label")
    if not selectors_included:
        errors.append("amd-gemma labels must be included in workload selectors")

    config_patch = _read_yaml(OVERLAY / "patch-configmap.yaml")
    config_data = config_patch.get("data", {})
    if config_data.get("LLM_PROVIDER") != "amd_vllm":
        errors.append("config patch must set LLM_PROVIDER=amd_vllm")
    if not str(config_data.get("AMD_VLLM_BASE_URL", "")).endswith("/v1"):
        errors.append("AMD_VLLM_BASE_URL must point at the OpenAI-compatible /v1 route")
    if config_data.get("AUTH_ENFORCE") != "true":
        errors.append("AUTH_ENFORCE must be true for the judged overlay")
    if config_data.get("FRONTEND_BASE") != "http://localhost:3000":
        errors.append("judged overlay FRONTEND_BASE must match the localhost UI port-forward")
    if config_data.get("CORS_ORIGINS") != '["http://localhost:3000"]':
        errors.append("judged overlay CORS_ORIGINS must allow only the localhost UI origin")

    gpu_patch = _read_yaml(OVERLAY / "patch-gpu-inference.yaml")
    gpu_spec = gpu_patch.get("spec", {})
    if gpu_spec.get("replicas") != 1:
        errors.append("judged AMD overlay must default to one schedulable GPU replica")
    if gpu_spec.get("strategy", {}).get("type") != "Recreate":
        errors.append("single-GPU judged overlay must use a Recreate rollout")
    if int(gpu_spec.get("progressDeadlineSeconds", 0)) < 1800:
        errors.append("GPU rollout deadline must allow first-time Gemma weight loading")
    pod_spec = gpu_patch.get("spec", {}).get("template", {}).get("spec", {})
    node_selector = pod_spec.get("nodeSelector", {})
    if node_selector.get("accelerator") != "amd-instinct-mi300x":
        errors.append("GPU overlay must target the AMD Instinct node selector")
    if node_selector.get("kubernetes.io/arch") != "amd64":
        errors.append("GPU overlay must pin linux/amd64 node architecture")
    containers = pod_spec.get("containers", [])
    inference = next(
        (item for item in containers if isinstance(item, dict) and item.get("name") == "inference"),
        {},
    )
    env_by_name = {
        str(item.get("name")): item
        for item in inference.get("env", [])
        if isinstance(item, dict)
    }
    base_gpu = _read_first_yaml(BASE_GPU)
    base_containers = (
        base_gpu.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    )
    base_inference = next(
        (
            item
            for item in base_containers
            if isinstance(item, dict) and item.get("name") == "inference"
        ),
        {},
    )
    base_env_by_name = {
        str(item.get("name")): item
        for item in base_inference.get("env", [])
        if isinstance(item, dict)
    }
    api_secret_ref = (
        base_env_by_name.get("VLLM_API_KEY", {})
        .get("valueFrom", {})
        .get("secretKeyRef", {})
    )
    if (
        api_secret_ref.get("name") != "hrcc-secrets"
        or api_secret_ref.get("key") != "AMD_VLLM_API_KEY"
    ):
        errors.append(
            "GPU overlay must source VLLM_API_KEY from hrcc-secrets/AMD_VLLM_API_KEY"
        )
    inference_args = " ".join(str(item) for item in base_inference.get("args", []))
    if "--api-key" in inference_args:
        errors.append("GPU overlay must not expose the vLLM service key in process arguments")
    for env_name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        secret_ref = (
            env_by_name.get(env_name, {})
            .get("valueFrom", {})
            .get("secretKeyRef", {})
        )
        if secret_ref.get("name") != "hrcc-gpu-secrets" or secret_ref.get("key") != "HF_TOKEN":
            errors.append(
                f"GPU overlay must source {env_name} from hrcc-gpu-secrets/HF_TOKEN"
            )

    cache_patch = _read_yaml(OVERLAY / "patch-model-cache.yaml")
    if cache_patch.get("spec", {}).get("accessModes") != ["ReadWriteOnce"]:
        errors.append("judged single-GPU model cache must be writable with ReadWriteOnce")

    egress = _read_yaml(OVERLAY / "model-download-egress.yaml")
    egress_spec = egress.get("spec", {})
    if egress_spec.get("podSelector", {}).get("matchLabels", {}).get(
        "app.kubernetes.io/name"
    ) != "hrcc-gpu-inference":
        errors.append("model download egress must select only the GPU inference pod")
    egress_ports = [
        port
        for rule in egress_spec.get("egress", [])
        if isinstance(rule, dict)
        for port in rule.get("ports", [])
        if isinstance(port, dict)
    ]
    if not any(port.get("protocol") == "TCP" and port.get("port") == 443 for port in egress_ports):
        errors.append("GPU model download policy must allow HTTPS only")

    database_egress = _read_yaml(OVERLAY / "backend-database-egress.yaml")
    database_egress_spec = database_egress.get("spec", {})
    if database_egress_spec.get("podSelector", {}).get("matchLabels", {}).get(
        "app.kubernetes.io/name"
    ) != "hrcc-backend":
        errors.append("database egress must select only the backend pod")
    database_rules = [
        rule
        for rule in database_egress_spec.get("egress", [])
        if isinstance(rule, dict)
    ]
    database_ports = [
        port
        for rule in database_rules
        for port in rule.get("ports", [])
        if isinstance(port, dict)
    ]
    if not any(
        port.get("protocol") == "TCP" and port.get("port") == 5432
        for port in database_ports
    ):
        errors.append("backend database policy must allow PostgreSQL TCP port 5432")

    env_values = _read_env(OVERLAY / "hrcc-secrets.example.env")
    for key in (
        "AMD_VLLM_API_KEY",
        "ALLOWED_MODELS",
        "JWT_SECRET",
        "ADMIN_EMAIL",
        "ADMIN_PASSWORD",
        "DATABASE_URL",
    ):
        if key not in env_values:
            errors.append(f"secret example missing {key}")
    gpu_env_values = _read_env(OVERLAY / "hrcc-gpu-secrets.example.env")
    for key in ("GPU_MODEL_ID", "GPU_SERVED_MODEL_NAME", "HF_TOKEN"):
        if key not in gpu_env_values:
            errors.append(f"GPU secret example missing {key}")
    for key in ("GPU_MODEL_ID", "GPU_SERVED_MODEL_NAME", "HF_TOKEN"):
        if key in env_values:
            errors.append(f"backend secret example must not contain GPU-only key {key}")
    for key in (
        "AMD_VLLM_API_KEY",
        "ALLOWED_MODELS",
        "JWT_SECRET",
        "ADMIN_EMAIL",
        "ADMIN_PASSWORD",
        "DATABASE_URL",
    ):
        if key in gpu_env_values:
            errors.append(f"GPU secret example must not contain backend key {key}")
    model = gpu_env_values.get("GPU_MODEL_ID", "")
    served = gpu_env_values.get("GPU_SERVED_MODEL_NAME", "")
    allowed = [item.strip() for item in env_values.get("ALLOWED_MODELS", "").split(",")]
    if not _contains_gemma(model):
        errors.append("GPU_MODEL_ID must name a Gemma/Gamma-family model")
    if not _contains_gemma(served):
        errors.append("GPU_SERVED_MODEL_NAME must name a Gemma/Gamma-family served model")
    if served not in allowed:
        errors.append("ALLOWED_MODELS must include GPU_SERVED_MODEL_NAME")
    if not env_values.get("AMD_VLLM_API_KEY", "").startswith("replace-"):
        errors.append("secret example must not contain a real AMD_VLLM_API_KEY")
    if not env_values.get("JWT_SECRET", "").startswith("replace-"):
        errors.append("secret example must not contain a real JWT_SECRET")
    if not env_values.get("ADMIN_EMAIL", "").endswith(".invalid"):
        errors.append("secret example ADMIN_EMAIL must use a reserved placeholder domain")
    if not env_values.get("ADMIN_PASSWORD", "").startswith("replace-"):
        errors.append("secret example must not contain a real ADMIN_PASSWORD")
    if not gpu_env_values.get("HF_TOKEN", "").startswith("replace-"):
        errors.append("secret example must not contain a real HF_TOKEN")

    database_url = urlparse(env_values.get("DATABASE_URL", ""))
    if database_url.scheme not in {"postgres", "postgresql"}:
        errors.append("DATABASE_URL must use PostgreSQL")
    if not database_url.hostname:
        errors.append("DATABASE_URL must contain an explicit external PostgreSQL host")
    elif database_url.hostname.endswith(".svc.cluster.local"):
        errors.append(
            "DATABASE_URL must not claim an in-cluster PostgreSQL service that the overlay does not deploy"
        )

    readme = (OVERLAY / "README.md").read_text(encoding="utf-8")
    for required_text in (
        "PostgreSQL 16",
        "pgvector",
        "ADMIN_EMAIL",
        "ADMIN_PASSWORD",
        "hrcc-backend:1.0.0",
        "hrcc-frontend:1.0.0",
        "immutable registry digests",
        "kubectl -n hr-ai-system port-forward svc/hrcc-backend 8000:8000",
        "kubectl -n hr-ai-system port-forward svc/hrcc-frontend 3000:3000",
    ):
        if required_text not in readme:
            errors.append(f"overlay README missing judged deployment prerequisite: {required_text}")

    return errors


def main() -> int:
    errors = verify()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("AMD-hosted Gemma overlay passes static deployment contract checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
