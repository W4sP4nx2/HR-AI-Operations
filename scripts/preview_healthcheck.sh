#!/usr/bin/env bash
set -euo pipefail

# Verify a running local preview.
# Start with: bash scripts/local_preview.sh
# Then run this in another terminal.

HOST="${HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3001}"
BACKEND_URL="http://${HOST}:${BACKEND_PORT}"
FRONTEND_URL="http://${HOST}:${FRONTEND_PORT}"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 not found"
    exit 1
  fi
}

need curl
need python3

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "${tmpdir}"
}
trap cleanup EXIT

echo "Checking backend health: ${BACKEND_URL}/health"
curl -fsS "${BACKEND_URL}/health" > "${tmpdir}/health.json"
python3 - "${tmpdir}/health.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
data = payload["data"]
assert payload["success"] is True
assert data["status"] in {"healthy", "ok"}
print(f"  ok provider={data.get('llm_provider')} live={data.get('llm_enabled')} demo={data.get('demo_mode')}")
PY

echo "Checking Dynamic Capability Engine: ${BACKEND_URL}/lifecycle/capabilities"
curl -fsS "${BACKEND_URL}/lifecycle/capabilities" > "${tmpdir}/capabilities.json"
python3 - "${tmpdir}/capabilities.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
data = payload["data"]
providers = {item["provider_id"]: item["status"] for item in data["providers"]}
assert payload["success"] is True
assert providers["deterministic_fallback"] == "measured_local"
assert "fireworks" in providers
assert "amd_vllm_gemma" in providers
print(f"  ok providers={providers}")
PY

echo "Checking zero-spend cost controls: ${BACKEND_URL}/lifecycle/cost-controls"
curl -fsS "${BACKEND_URL}/lifecycle/cost-controls" > "${tmpdir}/cost-controls.json"
python3 - "${tmpdir}/cost-controls.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
data = payload["data"]
assert payload["success"] is True
assert data["ok"] is True
assert data["network_required"] is False
assert data["provider_key_required"] is False
print(f"  ok passed={data['passed_count']}/{data['gate_count']}")
PY

echo "Checking frontend response: ${FRONTEND_URL}"
html="$(curl -fsS "${FRONTEND_URL}")"
case "${html}" in
  *"Govern.ai"*)
    echo "  ok frontend title found"
    ;;
  *)
    echo "frontend did not return the expected title"
    exit 1
    ;;
esac

echo "Preview healthcheck passed."
