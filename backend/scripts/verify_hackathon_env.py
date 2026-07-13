"""Verify hackathon provider/deployment environment without making network calls.

This script is intentionally offline. It does not prove that a key is accepted
or that an AMD GPU is present; it proves that the process environment is shaped
for the chosen submission path before an operator spends provider or GPU time.

Usage:
  python -m scripts.verify_hackathon_env --mode fireworks-auth
  python -m scripts.verify_hackathon_env --mode amd-gemma
  python -m scripts.verify_hackathon_env --mode both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Literal

OFFICIAL_FIREWORKS_OPENAI_BASE = "https://api.fireworks.ai/inference/v1"


Mode = Literal["fireworks-auth", "amd-gemma", "both"]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _looks_like_key(value: str) -> bool:
    return len(value) >= 16 and " " not in value


def _allowed_models(env_name: str = "ALLOWED_MODELS") -> list[str]:
    raw = _env(env_name)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _contains_gemma(value: str) -> bool:
    """Require the official Gemma family spelling in technical identifiers."""
    return "gemma" in value.lower()


def fireworks_auth_checks(
    *,
    require_active_provider: bool = True,
    models_env: str = "ALLOWED_MODELS",
) -> list[Check]:
    """Validate the Fireworks Serverless auth profile used by hosted demos."""
    provider = _env("LLM_PROVIDER").lower()
    base_url = _env("FIREWORKS_BASE_URL").rstrip("/")
    models = _allowed_models(models_env)
    key = _env("FIREWORKS_API_KEY")
    checks = [
        Check(
            "FIREWORKS_API_KEY present",
            _looks_like_key(key),
            "set via secret manager or judge harness; never commit it",
        ),
        Check(
            "FIREWORKS_BASE_URL official OpenAI-compatible endpoint",
            base_url == OFFICIAL_FIREWORKS_OPENAI_BASE,
            f"expected={OFFICIAL_FIREWORKS_OPENAI_BASE} current={base_url or '<unset>'}",
        ),
        Check(
            f"{models_env} injected",
            bool(models),
            "comma-separated concrete Fireworks model ids; no code defaults",
        ),
        Check(
            f"{models_env} use Fireworks account model paths",
            bool(models)
            and all(model.startswith("accounts/") and "/models/" in model for model in models),
            f"models={models or '<unset>'}",
        ),
    ]
    if require_active_provider:
        checks.insert(
            0,
            Check(
                "LLM_PROVIDER=fireworks",
                provider == "fireworks",
                f"current={provider or '<unset>'}",
            ),
        )
    return checks


def amd_gemma_checks(
    *,
    require_active_provider: bool = True,
    models_env: str = "ALLOWED_MODELS",
) -> list[Check]:
    """Validate the self-hosted AMD ROCm/vLLM Gemma profile."""
    provider = _env("LLM_PROVIDER").lower()
    models = _allowed_models(models_env)
    served = _env("AMD_VLLM_SERVED_MODEL")
    model = _env("AMD_VLLM_MODEL")
    base_url = _env("AMD_VLLM_BASE_URL").rstrip("/")
    key = _env("AMD_VLLM_API_KEY")
    checks = [
        Check(
            "AMD_VLLM_MODEL points to Gemma",
            bool(model) and _contains_gemma(model),
            f"current={model or '<unset>'}",
        ),
        Check(
            "AMD_VLLM_SERVED_MODEL points to Gemma",
            bool(served) and _contains_gemma(served),
            f"current={served or '<unset>'}",
        ),
        Check(
            "AMD_VLLM_API_KEY present",
            _looks_like_key(key),
            "internal service key for the OpenAI-compatible vLLM endpoint",
        ),
        Check(
            "AMD_VLLM_BASE_URL ends with /v1",
            bool(base_url) and base_url.endswith("/v1"),
            f"current={base_url or '<unset>'}",
        ),
        Check(
            f"{models_env} contains served Gemma name",
            bool(served) and served in models,
            f"served={served or '<unset>'} allowed={models or '<unset>'}",
        ),
    ]
    if require_active_provider:
        checks.insert(
            0,
            Check(
                "LLM_PROVIDER=amd_vllm",
                provider == "amd_vllm",
                f"current={provider or '<unset>'}",
            ),
        )
    return checks


def amd_deployment_auth_checks() -> list[Check]:
    """Validate the judged application's auth/bootstrap boundary offline."""
    auth_enforce = _env("AUTH_ENFORCE").lower()
    open_registration = _env("AUTH_OPEN_REGISTRATION").lower()
    jwt_secret = _env("JWT_SECRET")
    admin_email = _env("ADMIN_EMAIL")
    admin_password = _env("ADMIN_PASSWORD")
    database_url = _env("DATABASE_URL")
    return [
        Check(
            "AUTH_ENFORCE=true",
            auth_enforce == "true",
            f"current={auth_enforce or '<unset>'}",
        ),
        Check(
            "AUTH_OPEN_REGISTRATION=false",
            open_registration == "false",
            f"current={open_registration or '<unset>'}",
        ),
        Check(
            "JWT_SECRET is production-shaped",
            _looks_like_key(jwt_secret)
            and "dev-insecure" not in jwt_secret.lower()
            and "replace" not in jwt_secret.lower(),
            "set a long random value via the deployment secret manager",
        ),
        Check(
            "first-run admin credentials present",
            "@" in admin_email and _looks_like_key(admin_password),
            "ADMIN_EMAIL and a strong ADMIN_PASSWORD are required when registration is closed",
        ),
        Check(
            "DATABASE_URL uses PostgreSQL",
            database_url.startswith(("postgresql://", "postgresql+")),
            "the judged multi-replica profile requires PostgreSQL/pgvector",
        ),
    ]


def checks_for_mode(mode: Mode) -> list[Check]:
    if mode == "fireworks-auth":
        return fireworks_auth_checks()
    if mode == "amd-gemma":
        return [*amd_gemma_checks(), *amd_deployment_auth_checks()]
    provider = _env("LLM_PROVIDER").lower()
    return [
        Check(
            "LLM_PROVIDER selects a supported live profile",
            provider in {"fireworks", "amd_vllm"},
            f"current={provider or '<unset>'}",
        ),
        *fireworks_auth_checks(
            require_active_provider=False,
            models_env="FIREWORKS_ALLOWED_MODELS",
        ),
        *amd_gemma_checks(
            require_active_provider=False,
            models_env="AMD_VLLM_ALLOWED_MODELS",
        ),
        *amd_deployment_auth_checks(),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["fireworks-auth", "amd-gemma", "both"],
        default="both",
        help="Environment profile to validate.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )
    args = parser.parse_args(argv)

    checks = checks_for_mode(args.mode)
    ok = all(check.ok for check in checks)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "ok": ok,
                    "checks": [
                        {
                            "name": check.name,
                            "ok": check.ok,
                            "detail": check.detail,
                        }
                        for check in checks
                    ],
                },
                indent=2,
            )
        )
    else:
        print(f"Hackathon environment profile: {args.mode}")
        for check in checks:
            status = "PASS" if check.ok else "FAIL"
            print(f"[{status}] {check.name} — {check.detail}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
