"""No-network tests for the AMD/Gemma judge preflight orchestrator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "preflight_amd_gemma_judge.py"
SPEC = importlib.util.spec_from_file_location("preflight_amd_gemma_judge", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


def test_static_preflight_composes_existing_authoritative_verifiers(monkeypatch) -> None:
    calls: list[tuple[str, list[str], Path]] = []

    def fake_run(name: str, command: list[str], *, cwd: Path = ROOT, timeout: float = 180):
        calls.append((name, command, cwd))
        return preflight.Check(name, True, "ok")

    monkeypatch.setattr(preflight, "_run", fake_run)

    checks = preflight.static_checks()

    assert all(check.ok for check in checks)
    assert [name for name, _command, _cwd in calls] == [
        "amd-gemma-overlay-contract",
        "amd-gemma-kustomize-render",
        "amd-compose-and-platform-contract",
        "hackathon-claims-contract",
    ]
    assert calls[1][1] == ["kubectl", "kustomize", "deploy/k8s/overlays/amd-gemma"]


def test_backend_preflight_proves_amd_route_and_browser_key_isolation(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", "judge-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-test-password")

    def fake_get(url: str, **_kwargs):
        if url.endswith("/health"):
            return (
                {
                    "success": True,
                    "data": {
                        "auth_enforced": True,
                        "llm_provider": "amd_vllm",
                        "llm_enabled": True,
                        "llm_config_issues": [],
                        "byok_supported": False,
                    },
                },
                {},
            )
        assert url.endswith("/byok/verify")
        return (
            {
                "success": True,
                "data": {
                    "valid": False,
                    "status": "unsupported",
                    "provider": "amd_vllm",
                },
            },
            {"x-byok": "0"},
        )

    monkeypatch.setattr(preflight, "_get_json", fake_get)
    monkeypatch.setattr(
        preflight,
        "_post_json",
        lambda *_args, **_kwargs: {
            "success": True,
            "data": {
                "token": "fixture-jwt-not-secret",
                "user": {"email": "judge-admin@example.com", "role": "admin"},
            },
        },
    )

    checks = preflight._backend_checks("http://backend.test", timeout=1)

    assert {check.name for check in checks} == {
        "amd-app-auth-enforced",
        "amd-backend-provider",
        "amd-browser-byok-disabled",
        "amd-backend-config",
        "amd-first-admin-login",
        "amd-service-auth-boundary",
    }
    assert all(check.ok for check in checks)


def test_backend_preflight_rejects_exposed_amd_byok(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", "judge-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-test-password")

    def fake_get(url: str, **_kwargs):
        if url.endswith("/health"):
            return (
                {
                    "data": {
                        "auth_enforced": True,
                        "llm_provider": "amd_vllm",
                        "llm_enabled": True,
                        "llm_config_issues": [],
                        "byok_supported": True,
                    }
                },
                {},
            )
        return (
            {"data": {"status": "verified", "provider": "amd_vllm"}},
            {"x-byok": "1"},
        )

    monkeypatch.setattr(preflight, "_get_json", fake_get)
    monkeypatch.setattr(
        preflight,
        "_post_json",
        lambda *_args, **_kwargs: {
            "success": True,
            "data": {
                "token": "fixture-jwt-not-secret",
                "user": {"email": "judge-admin@example.com", "role": "admin"},
            },
        },
    )

    checks = {check.name: check for check in preflight._backend_checks("http://x", timeout=1)}

    assert checks["amd-browser-byok-disabled"].ok is False
    assert checks["amd-service-auth-boundary"].ok is False


def test_backend_preflight_requires_admin_credentials(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(
        preflight,
        "_get_json",
        lambda url, **_kwargs: (
            {
                "data": {
                    "auth_enforced": True,
                    "llm_provider": "amd_vllm",
                    "llm_enabled": True,
                    "llm_config_issues": [],
                    "byok_supported": False,
                    "status": "unsupported" if url.endswith("/byok/verify") else "healthy",
                    "provider": "amd_vllm",
                }
            },
            {"x-byok": "0"},
        ),
    )

    checks = {check.name: check for check in preflight._backend_checks("http://x", timeout=1)}

    assert checks["amd-first-admin-login"].ok is False
    assert "ADMIN_EMAIL" in checks["amd-first-admin-login"].detail
