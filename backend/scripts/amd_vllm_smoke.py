# ruff: noqa: E402
"""Live AMD/vLLM Gemma smoke test.

Run only on the credentialed AMD-hosted Gemma environment:

  LLM_PROVIDER=amd_vllm AMD_VLLM_API_KEY=... AMD_VLLM_BASE_URL=http://.../v1 \
  ALLOWED_MODELS=amd-gemma-3-27b-it python -m scripts.amd_vllm_smoke

The script proves the OpenAI-compatible serving surface, not benchmark
performance. Capture hardware, ROCm/vLLM versions, latency, and correctness
separately before publishing speed claims.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.runtime_key import llm_config_issues, llm_provider, server_api_key


def _base_url() -> str:
    return os.environ.get("AMD_VLLM_BASE_URL", "").strip().rstrip("/")


def _serving_root(base_url: str) -> str:
    """Return http://host:port from an OpenAI-compatible http://host:port/v1 URL."""
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")] or "/"
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", "")).rstrip("/")


def _allowed_models() -> list[str]:
    raw = os.environ.get("ALLOWED_MODELS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _gemma_models(models: list[str]) -> list[str]:
    return [model for model in models if "gemma" in model.lower() or "gamma" in model.lower()]


def _get_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    import httpx

    response = httpx.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    import httpx

    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _model_ids(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    return ids


def _completion_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message", {})
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def run_smoke(timeout: float = 30.0) -> dict[str, Any]:
    """Run the live smoke test and return non-secret evidence."""
    if llm_provider() != "amd_vllm":
        raise RuntimeError("LLM_PROVIDER must be 'amd_vllm' for this smoke test")

    issues = llm_config_issues()
    if issues:
        raise RuntimeError("AMD/vLLM config incomplete: " + "; ".join(issues))

    allowed = _allowed_models()
    candidates = _gemma_models(allowed)
    if not candidates:
        raise RuntimeError("ALLOWED_MODELS must include a Gemma/Gamma-family served model")
    model_id = candidates[0]
    base_url = _base_url()
    headers = {"Authorization": f"Bearer {server_api_key()}"}

    started = time.perf_counter()
    health = _get_json(f"{_serving_root(base_url)}/health", headers=headers, timeout=timeout)
    health_ms = round((time.perf_counter() - started) * 1000, 3)

    started = time.perf_counter()
    model_payload = _get_json(f"{base_url}/models", headers=headers, timeout=timeout)
    models_ms = round((time.perf_counter() - started) * 1000, 3)
    served_models = _model_ids(model_payload)
    if model_id not in served_models:
        raise RuntimeError(f"served model {model_id!r} not returned by /v1/models")

    chat_body = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    started = time.perf_counter()
    chat_payload = _post_json(
        f"{base_url}/chat/completions",
        headers={**headers, "Content-Type": "application/json"},
        payload=chat_body,
        timeout=timeout,
    )
    chat_ms = round((time.perf_counter() - started) * 1000, 3)
    answer = _completion_text(chat_payload)
    if "OK" not in answer.upper():
        raise RuntimeError(f"chat smoke failed; response={answer!r}")

    return {
        "provider": "amd_vllm",
        "base_url_path": urlsplit(base_url).path,
        "model": model_id,
        "health_ok": bool(health is not None),
        "served_models": served_models,
        "latency_ms": {
            "health": health_ms,
            "models": models_ms,
            "chat": chat_ms,
        },
        "chat_smoke": "ok",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a controlled live AMD/vLLM Gemma smoke test.")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        result = run_smoke(timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001 - smoke tests are operator-facing
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"AMD/vLLM smoke failed: {exc}")
        return 1

    if args.json:
        print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    else:
        print(
            "AMD/vLLM Gemma smoke ok: "
            f"model={result['model']} "
            f"chat_ms={result['latency_ms']['chat']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
