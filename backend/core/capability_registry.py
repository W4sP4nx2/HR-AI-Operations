"""Evidence-driven runtime capability discovery.

This module performs bounded, no-secret discovery for the product dashboard.
It does not call hosted inference providers. Live Fireworks or AMD/vLLM proof
still comes from smoke tests and evidence bundles; this registry only reports
what is configured, what is measured locally, and what remains gated.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.config import settings
from core.runtime_key import llm_active, llm_provider, looks_like_key

CapabilityStatus = Literal[
    "proven",
    "measured_local",
    "configured",
    "live_gated",
    "not_configured",
    "unavailable",
]


@dataclass(frozen=True)
class RuntimeMeasurement:
    """A concrete measurement captured in this process."""

    name: str
    value: float
    unit: str
    evidence_level: str
    notes: str


@dataclass(frozen=True)
class ProviderCapability:
    """Secret-free inference provider posture."""

    provider_id: str
    provider_type: str
    status: CapabilityStatus
    models_available: list[str]
    supports_batch: bool
    supports_streaming: bool
    supports_prompt_cache: bool
    supports_json_schema: bool
    supports_byok: bool
    live_enabled: bool
    missing_inputs: list[str]
    evidence_required: list[str]
    measurements: list[RuntimeMeasurement] = field(default_factory=list)
    route_fit: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HardwareCapability:
    """Secret-free local hardware/runtime posture."""

    hardware_id: str
    vendor: str
    status: CapabilityStatus
    detector: str
    evidence_required: list[str]
    runtime_evidence_file: str | None = None
    device_names: list[str] = field(default_factory=list)
    measurements: list[RuntimeMeasurement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RoutingDecision:
    """A no-call routing decision derived from current capability evidence."""

    task_type: str
    selected_provider: str
    status: CapabilityStatus
    reason: str
    evidence_used: list[str]
    live_call_allowed: bool


@dataclass(frozen=True)
class CapabilitySnapshot:
    """Whole-system capability snapshot for product and judge views."""

    generated_at_unix: float
    claim_policy: str
    demo_mode: bool
    active_provider: str
    providers: list[ProviderCapability]
    hardware: list[HardwareCapability]
    routing: list[RoutingDecision]
    required_live_inputs: dict[str, list[str]]
    safe_wording: list[str]

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-serializable payload."""
        return asdict(self)


def capability_snapshot() -> dict[str, Any]:
    """Return the current no-secret capability snapshot."""
    providers = _discover_providers()
    hardware = _discover_hardware()
    routing = _route_examples(providers, hardware)
    active = llm_provider() or "deterministic"
    return CapabilitySnapshot(
        generated_at_unix=time.time(),
        claim_policy=(
            "Do not claim Fireworks, AMD, Gemma, latency, throughput, or cost "
            "performance until the corresponding live smoke/evidence artifact is present."
        ),
        demo_mode=bool(settings.demo_mode or settings.mock_llm or not llm_active()),
        active_provider=active,
        providers=providers,
        hardware=hardware,
        routing=routing,
        required_live_inputs={
            "fireworks": [
                "FIREWORKS_API_KEY",
                "FIREWORKS_BASE_URL",
                "ALLOWED_MODELS with exact approved model IDs",
                "optional FIREWORKS_VISION_MODEL for scanned-resume VLM",
            ],
            "amd_vllm_gemma": [
                "AMD_VLLM_BASE_URL",
                "AMD_VLLM_API_KEY or explicit no-auth gateway policy",
                "AMD_VLLM_SERVED_MODEL containing the Gemma-family served name",
                "ALLOWED_MODELS containing the same served model",
                "AMD_RUNTIME_EVIDENCE_FILE from scripts/capture_amd_runtime_evidence.py",
            ],
        },
        safe_wording=[
            "Local preview is zero-spend and deterministic.",
            "Fireworks route is configured only when keys and allowlisted models are present.",
            "AMD-hosted Gemma is deployable until live ROCm/vLLM evidence proves it is running.",
            "Performance is measured per environment; no static speedup or cost claims are published.",
        ],
    ).as_dict()


def _discover_providers() -> list[ProviderCapability]:
    return [
        _deterministic_provider(),
        _fireworks_provider(),
        _amd_vllm_provider(),
    ]


def _deterministic_provider() -> ProviderCapability:
    measurement = _measure_fallback_router()
    return ProviderCapability(
        provider_id="deterministic_fallback",
        provider_type="local_no_network",
        status="measured_local",
        models_available=["hashing_embeddings", "keyword_policy_fallback", "schema_certifier"],
        supports_batch=False,
        supports_streaming=True,
        supports_prompt_cache=False,
        supports_json_schema=True,
        supports_byok=False,
        live_enabled=True,
        missing_inputs=[],
        evidence_required=[],
        measurements=[measurement],
        route_fit=["local_preview", "unit_tests", "cost_certification", "offline_demo"],
    )


def _fireworks_provider() -> ProviderCapability:
    models = _allowed_models()
    missing = []
    if not looks_like_key(os.environ.get("FIREWORKS_API_KEY", settings.fireworks_api_key)):
        missing.append("FIREWORKS_API_KEY")
    if not os.environ.get("FIREWORKS_BASE_URL", settings.fireworks_base_url).strip():
        missing.append("FIREWORKS_BASE_URL")
    if not models:
        missing.append("ALLOWED_MODELS")
    configured = len(missing) == 0
    return ProviderCapability(
        provider_id="fireworks",
        provider_type="serverless_or_batch",
        status="configured" if configured else "live_gated",
        models_available=models,
        supports_batch=True,
        supports_streaming=True,
        supports_prompt_cache=True,
        supports_json_schema=True,
        supports_byok=True,
        live_enabled=llm_provider() == "fireworks" and configured and llm_active(),
        missing_inputs=missing,
        evidence_required=[
            "python -m scripts.fireworks_smoke --enable-cost-tracking",
            "BYOK or server key verification",
            "audit log entry with model_id and estimated_spend_usd",
        ],
        route_fit=["policy_qa", "case_triage", "resume_vlm", "bulk_batch"],
    )


def _amd_vllm_provider() -> ProviderCapability:
    models = _allowed_models()
    served_model = os.environ.get("AMD_VLLM_SERVED_MODEL", "").strip()
    missing = []
    if not os.environ.get("AMD_VLLM_BASE_URL", settings.amd_vllm_base_url).strip():
        missing.append("AMD_VLLM_BASE_URL")
    if not looks_like_key(os.environ.get("AMD_VLLM_API_KEY", settings.amd_vllm_api_key)):
        missing.append("AMD_VLLM_API_KEY")
    if not served_model:
        missing.append("AMD_VLLM_SERVED_MODEL")
    if served_model and served_model not in models:
        missing.append("ALLOWED_MODELS must include AMD_VLLM_SERVED_MODEL")
    if served_model and "gemma" not in served_model.lower() and "gamma" not in served_model.lower():
        missing.append("AMD_VLLM_SERVED_MODEL must be Gemma/Gamma-family for the track")

    runtime = _load_amd_runtime_evidence()
    status: CapabilityStatus
    if runtime["valid"]:
        status = "proven"
    elif missing:
        status = "live_gated"
    else:
        status = "configured"

    measurements = []
    if runtime["valid"] and runtime.get("device_count") is not None:
        measurements.append(
            RuntimeMeasurement(
                name="amd_runtime_device_count",
                value=float(runtime["device_count"]),
                unit="devices",
                evidence_level="runtime_evidence",
                notes="Captured from AMD runtime evidence file; not a throughput benchmark.",
            )
        )

    return ProviderCapability(
        provider_id="amd_vllm_gemma",
        provider_type="self_hosted_openai_compatible",
        status=status,
        models_available=[served_model] if served_model else [],
        supports_batch=False,
        supports_streaming=True,
        supports_prompt_cache=False,
        supports_json_schema=True,
        supports_byok=True,
        live_enabled=llm_provider() == "amd_vllm" and status == "proven" and llm_active(),
        missing_inputs=missing + ([] if runtime["valid"] else ["AMD_RUNTIME_EVIDENCE_FILE"]),
        evidence_required=[
            "python -m scripts.amd_vllm_smoke --json",
            "python3 scripts/capture_amd_runtime_evidence.py --output <file>",
            "python3 scripts/verify_amd_runtime_evidence.py <file>",
        ],
        measurements=measurements,
        route_fit=["sensitive_hr_review", "air_gapped_demo", "amd_hosted_gemma_judging"],
    )


def _discover_hardware() -> list[HardwareCapability]:
    runtime = _load_amd_runtime_evidence()
    notes: list[str] = []
    if shutil.which("rocm-smi") is None:
        notes.append("rocm-smi not found in this environment")
    else:
        notes.append("rocm-smi command exists; runtime evidence still required for claims")
    if not runtime["valid"] and runtime.get("errors"):
        notes.extend(str(error) for error in runtime["errors"])

    return [
        HardwareCapability(
            hardware_id="local_rocm_gpu",
            vendor="amd",
            status="proven" if runtime["valid"] else "unavailable",
            detector="AMD_RUNTIME_EVIDENCE_FILE + optional rocm-smi",
            evidence_required=[
                "validated AMD runtime evidence",
                "ROCm/vLLM versions",
                "successful Gemma smoke run",
            ],
            runtime_evidence_file=runtime.get("path"),
            device_names=list(runtime.get("device_names") or []),
            notes=notes,
        )
    ]


def _route_examples(
    providers: list[ProviderCapability],
    hardware: list[HardwareCapability],
) -> list[RoutingDecision]:
    by_id = {provider.provider_id: provider for provider in providers}
    amd = by_id["amd_vllm_gemma"]
    fireworks = by_id["fireworks"]
    fallback = by_id["deterministic_fallback"]
    amd_hw_proven = any(item.vendor == "amd" and item.status == "proven" for item in hardware)

    sensitive_provider = amd if amd.status == "proven" and amd_hw_proven else fallback
    realtime_provider = fireworks if fireworks.live_enabled else fallback
    batch_provider = fireworks if fireworks.live_enabled and fireworks.supports_batch else fallback

    return [
        _decision(
            "sensitive_hr_or_pii",
            sensitive_provider,
            "AMD route is selected only after runtime evidence proves local AMD/Gemma. "
            "Until then, deterministic fallback avoids external disclosure in preview.",
            ["amd_runtime_evidence" if sensitive_provider is amd else "local_no_network"],
        ),
        _decision(
            "real_time_policy_chat",
            realtime_provider,
            "Use live Fireworks only when provider config and key are present; otherwise local fallback.",
            ["fireworks_config" if realtime_provider is fireworks else "local_no_network"],
        ),
        _decision(
            "bulk_resume_or_bias_batch",
            batch_provider,
            "Batch route requires live Fireworks availability; local preview does not make batch claims.",
            ["fireworks_batch_config" if batch_provider is fireworks else "local_no_network"],
        ),
    ]


def _decision(
    task_type: str,
    provider: ProviderCapability,
    reason: str,
    evidence_used: list[str],
) -> RoutingDecision:
    return RoutingDecision(
        task_type=task_type,
        selected_provider=provider.provider_id,
        status=provider.status,
        reason=reason,
        evidence_used=evidence_used,
        live_call_allowed=provider.live_enabled and provider.status in {"configured", "proven"},
    )


def _measure_fallback_router(samples: int = 5) -> RuntimeMeasurement:
    """Measure a deterministic local operation used by fallback routing."""
    latencies: list[float] = []
    payload = b"policy:remote-work:version-2026"
    for _ in range(max(1, samples)):
        started = time.perf_counter()
        hashlib.sha256(payload).hexdigest()
        latencies.append((time.perf_counter() - started) * 1000.0)
    return RuntimeMeasurement(
        name="fallback_hash_route_p50",
        value=round(statistics.median(latencies), 6),
        unit="ms",
        evidence_level="measured_local",
        notes=f"Measured on {platform.system()} {platform.machine()} without provider calls.",
    )


def _allowed_models() -> list[str]:
    raw = os.environ.get("ALLOWED_MODELS", settings.allowed_models)
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def _load_amd_runtime_evidence() -> dict[str, Any]:
    path = os.environ.get("AMD_RUNTIME_EVIDENCE_FILE", "").strip()
    if not path:
        return {"valid": False, "path": None, "errors": ["AMD_RUNTIME_EVIDENCE_FILE is unset"]}
    evidence_path = Path(path)
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - evidence status must degrade cleanly
        return {"valid": False, "path": path, "errors": [f"could not read evidence: {exc}"]}

    device_names = _extract_device_names(payload)
    device_count = _extract_device_count(payload, device_names)
    errors = []
    if not device_names:
        errors.append("runtime evidence has no device names")
    if not any(_looks_like_amd_device(name) for name in device_names):
        errors.append("runtime evidence does not identify an AMD device")
    if not _has_runtime_version(payload, "torch") and not _has_runtime_version(payload, "rocm"):
        errors.append("runtime evidence is missing torch/rocm version detail")
    return {
        "valid": not errors,
        "path": path,
        "errors": errors,
        "device_names": device_names,
        "device_count": device_count,
    }


def _extract_device_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("device_names", "devices", "gpu_names"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("device_name") or item.get("product_name")
                    if isinstance(name, str):
                        names.append(name)
    nested = payload.get("cuda") or payload.get("rocm") or {}
    if isinstance(nested, dict):
        value = nested.get("device_names") or nested.get("devices")
        if isinstance(value, list):
            names.extend(str(item) for item in value if item)
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))


def _extract_device_count(payload: dict[str, Any], names: list[str]) -> int | None:
    for key in ("device_count", "gpu_count"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
    nested = payload.get("cuda") or payload.get("rocm") or {}
    if isinstance(nested, dict) and isinstance(nested.get("device_count"), int):
        return nested["device_count"]
    return len(names) if names else None


def _has_runtime_version(payload: dict[str, Any], key: str) -> bool:
    raw = json.dumps(payload, sort_keys=True).lower()
    return key in raw and "version" in raw


def _looks_like_amd_device(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in ("amd", "instinct", "radeon", "gfx", "mi2", "mi3"))
