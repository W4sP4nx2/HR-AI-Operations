"""Live backend BYOK verification smoke test.

This script proves the running FastAPI backend accepts a request-scoped key via
``X-Client-LLM-Key`` and reports the expected provider. It never prints the key.

Example:
  LLM_PROVIDER=fireworks FIREWORKS_API_KEY=... \
    python -m scripts.byok_smoke --provider fireworks

AMD/vLLM deliberately does not support browser BYOK: its API key is a private
backend-to-inference service credential. Use ``scripts.amd_vllm_smoke`` for that
route instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.runtime_key import llm_provider, server_api_key  # noqa: E402

Provider = Literal["fireworks"]


def _backend_base() -> str:
    return os.environ.get("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")


def _expected_provider(cli_provider: str | None) -> Provider:
    provider = (cli_provider or llm_provider()).strip().lower()
    if provider != "fireworks":
        raise RuntimeError("BYOK smoke is supported only for provider 'fireworks'")
    return provider  # type: ignore[return-value]


def _get_verify(url: str, key: str, timeout: float) -> dict[str, Any]:
    import httpx

    response = httpx.get(url, headers={"X-Client-LLM-Key": key}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _verification_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def run_smoke(*, provider: Provider, timeout: float = 10.0) -> dict[str, Any]:
    if provider != "fireworks":
        raise RuntimeError("BYOK smoke is supported only for provider 'fireworks'")
    configured_provider = llm_provider()
    if configured_provider != provider:
        raise RuntimeError(f"local LLM_PROVIDER is {configured_provider!r}, expected {provider!r}")
    key = server_api_key()
    if not key:
        raise RuntimeError(f"no server key configured for {provider}")

    url = f"{_backend_base()}/byok/verify"
    started = time.perf_counter()
    payload = _get_verify(url, key, timeout)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    data = _verification_data(payload)

    status = data.get("status")
    reported_provider = data.get("provider")
    if status != "verified":
        raise RuntimeError(f"BYOK verification status was {status!r}")
    if reported_provider != provider:
        raise RuntimeError(f"BYOK provider was {reported_provider!r}, expected {provider!r}")

    return {
        "provider": provider,
        "status": "verified",
        "backend_base": _backend_base(),
        "latency_ms": elapsed_ms,
        "key_echoed": key in json.dumps(payload),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a controlled live BYOK verification smoke.")
    parser.add_argument("--provider", choices=["fireworks"], default=None)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        provider = _expected_provider(args.provider)
        result = run_smoke(provider=provider, timeout=args.timeout)
        if result["key_echoed"]:
            raise RuntimeError("backend response echoed the secret key")
    except Exception as exc:  # noqa: BLE001 - smoke tests are operator-facing
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"BYOK smoke failed: {exc}")
        return 1

    if args.json:
        print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    else:
        print(f"BYOK smoke ok: provider={result['provider']} latency_ms={result['latency_ms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
