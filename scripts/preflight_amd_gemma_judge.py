"""Run the non-secret preflight for an AMD-hosted Gemma judging session.

Static mode proves that the checked-in deployment and claims contracts render.
Live mode additionally requires a running AMD-profile backend, a reachable
AMD/vLLM endpoint, and previously captured runtime evidence from real hardware.

Examples:
  python scripts/preflight_amd_gemma_judge.py --mode static

  BACKEND_BASE_URL=http://localhost:8000 \
  LLM_PROVIDER=amd_vllm \
  AMD_VLLM_BASE_URL=http://localhost:8001/v1 \
  AMD_VLLM_API_KEY=... \
  ALLOWED_MODELS=amd-gemma-3-27b-it \
  ADMIN_EMAIL=judge-admin@example.com \
  ADMIN_PASSWORD=... \
  python scripts/preflight_amd_gemma_judge.py --mode live \
    --amd-runtime-evidence /tmp/amd-runtime.json

The command never prints credentials. Browser BYOK isolation is checked with a
fixed dummy value, not with ``AMD_VLLM_API_KEY``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
Mode = Literal["static", "live"]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _run(name: str, command: list[str], *, cwd: Path = ROOT, timeout: float = 180.0) -> Check:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout.strip() or completed.stderr.strip() or "no output"
    if completed.returncode == 0 and len(output) > 300:
        detail = f"command completed successfully; output_bytes={len(output.encode('utf-8'))}"
    else:
        detail = output[-1000:]
    return Check(name=name, ok=completed.returncode == 0, detail=detail)


def static_checks() -> list[Check]:
    """Validate the repository deployment contract without credentials or a cluster."""
    return [
        _run(
            "amd-gemma-overlay-contract",
            [sys.executable, "scripts/verify_amd_gemma_overlay.py"],
        ),
        _run(
            "amd-gemma-kustomize-render",
            ["kubectl", "kustomize", "deploy/k8s/overlays/amd-gemma"],
        ),
        _run(
            "amd-compose-and-platform-contract",
            [sys.executable, "scripts/verify_platform_manifests.py"],
        ),
        _run(
            "hackathon-claims-contract",
            [sys.executable, "scripts/verify_hackathon_completion_audit.py"],
        ),
    ]


def _get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[dict[str, Any], dict[str, str]]:
    request = Request(url, headers=headers or {}, method="GET")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator URL
        payload = json.loads(response.read().decode("utf-8"))
        response_headers = {name.lower(): value for name, value in response.headers.items()}
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} did not return a JSON object")
    return payload, response_headers


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator URL
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{url} did not return a JSON object")
    return value


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("data")
    return value if isinstance(value, dict) else payload


def _backend_checks(backend_base: str, *, timeout: float) -> list[Check]:
    checks: list[Check] = []
    try:
        health_payload, _ = _get_json(f"{backend_base}/health", timeout=timeout)
        health = _data(health_payload)
    except Exception as exc:  # noqa: BLE001 - operator-facing diagnostics
        return [Check("amd-backend-health", False, f"backend health failed: {exc}")]

    provider = health.get("llm_provider")
    byok = health.get("byok_supported")
    issues = health.get("llm_config_issues")
    checks.extend(
        [
            Check(
                "amd-app-auth-enforced",
                health.get("auth_enforced") is True,
                f"auth_enforced={health.get('auth_enforced')!r}",
            ),
            Check(
                "amd-backend-provider",
                provider == "amd_vllm",
                f"llm_provider={provider!r}",
            ),
            Check(
                "amd-browser-byok-disabled",
                byok is False,
                f"byok_supported={byok!r}",
            ),
            Check(
                "amd-backend-config",
                health.get("llm_enabled") is True and issues == [],
                f"llm_enabled={health.get('llm_enabled')!r}; issues={issues!r}",
            ),
        ]
    )

    admin_email = os.environ.get("ADMIN_EMAIL", "").strip()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if not admin_email or not admin_password:
        checks.append(
            Check(
                "amd-first-admin-login",
                False,
                "ADMIN_EMAIL and ADMIN_PASSWORD are required for live login proof",
            )
        )
    else:
        try:
            login_payload = _post_json(
                f"{backend_base}/auth/login",
                {"email": admin_email, "password": admin_password},
                timeout=timeout,
            )
            login = _data(login_payload)
            user = login.get("user") if isinstance(login.get("user"), dict) else {}
            login_ok = (
                login_payload.get("success") is True
                and bool(login.get("token"))
                and user.get("role") == "admin"
                and user.get("email") == admin_email.lower()
            )
            checks.append(
                Check(
                    "amd-first-admin-login",
                    login_ok,
                    f"authenticated={login_ok}; role={user.get('role')!r}",
                )
            )
        except Exception as exc:  # noqa: BLE001 - operator-facing diagnostics
            checks.append(Check("amd-first-admin-login", False, f"login failed: {exc}"))

    try:
        boundary_payload, boundary_headers = _get_json(
            f"{backend_base}/byok/verify",
            headers={"X-Client-LLM-Key": "judge-boundary-probe-not-a-secret"},
            timeout=timeout,
        )
        boundary = _data(boundary_payload)
        boundary_ok = (
            boundary.get("status") == "unsupported"
            and boundary.get("provider") == "amd_vllm"
            and boundary_headers.get("x-byok") == "0"
        )
        detail = (
            f"status={boundary.get('status')!r}; provider={boundary.get('provider')!r}; "
            f"x-byok={boundary_headers.get('x-byok')!r}"
        )
        checks.append(Check("amd-service-auth-boundary", boundary_ok, detail))
    except Exception as exc:  # noqa: BLE001 - operator-facing diagnostics
        checks.append(Check("amd-service-auth-boundary", False, str(exc)))
    return checks


def live_checks(runtime_evidence: Path, *, backend_base: str, timeout: float) -> list[Check]:
    """Prove config, backend routing, service auth, model response, and AMD runtime."""
    checks = static_checks()
    checks.extend(
        [
            _run(
                "amd-gemma-environment",
                [
                    sys.executable,
                    "-m",
                    "scripts.verify_hackathon_env",
                    "--mode",
                    "amd-gemma",
                    "--json",
                ],
                cwd=BACKEND,
                timeout=timeout,
            ),
            _run(
                "amd-runtime-evidence",
                [
                    sys.executable,
                    "scripts/verify_amd_runtime_evidence.py",
                    str(runtime_evidence),
                    "--json",
                ],
                timeout=timeout,
            ),
            _run(
                "amd-vllm-gemma-smoke",
                [sys.executable, "-m", "scripts.amd_vllm_smoke", "--json"],
                cwd=BACKEND,
                timeout=timeout,
            ),
        ]
    )
    checks.extend(_backend_checks(backend_base, timeout=timeout))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["static", "live"], default="static")
    parser.add_argument("--amd-runtime-evidence", type=Path)
    parser.add_argument(
        "--backend-base",
        default=os.environ.get("BACKEND_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "live" and args.amd_runtime_evidence is None:
        parser.error("--amd-runtime-evidence is required in live mode")

    try:
        if args.mode == "live":
            assert args.amd_runtime_evidence is not None
            checks = live_checks(
                args.amd_runtime_evidence,
                backend_base=args.backend_base.rstrip("/"),
                timeout=args.timeout,
            )
        else:
            checks = static_checks()
    except Exception as exc:  # noqa: BLE001 - operator-facing diagnostics
        checks = [Check("preflight-execution", False, str(exc))]

    ok = all(check.ok for check in checks)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "mode": args.mode,
                    "checks": [asdict(check) for check in checks],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for check in checks:
            status = "PASS" if check.ok else "FAIL"
            print(f"[{status}] {check.name}: {check.detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
