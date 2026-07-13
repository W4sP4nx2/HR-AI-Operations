#!/usr/bin/env bash
set -euo pipefail

# Judge-day smoke check for the Docker hackathon overlay. This verifies the
# running product and seeded demo state without making any provider call.

HOST="${HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_URL="http://${HOST}:${BACKEND_PORT}"
FRONTEND_URL="http://${HOST}:${FRONTEND_PORT}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "$1 not found" >&2; exit 1; }
}

need curl
need python3

tmpdir="$(mktemp -d)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT

get() {
  local name="$1" url="$2"
  echo "[check] ${name}"
  curl --fail --silent --show-error --retry 20 --retry-delay 1 \
    --retry-connrefused "$url" >"$tmpdir/$name.json"
}

get health "${BACKEND_URL}/health"
python3 - "$tmpdir/health.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("success") is True, payload
data = payload["data"]
assert data["status"] in {"healthy", "ok"}, data
assert data["demo_mode"] is True, data
assert data["llm_enabled"] is False, data
print(f"  healthy: provider={data['llm_provider']} deterministic_demo=true")
PY

get capabilities "${BACKEND_URL}/lifecycle/capabilities"
python3 - "$tmpdir/capabilities.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("success") is True, payload
providers = {item["provider_id"]: item["status"] for item in payload["data"]["providers"]}
assert providers.get("deterministic_fallback") == "measured_local", providers
assert providers.get("fireworks") == "live_gated", providers
assert providers.get("amd_vllm_gemma") == "live_gated", providers
print("  capability boundary: fallback=measured_local fireworks=live_gated amd=live_gated")
PY

get cost-controls "${BACKEND_URL}/lifecycle/cost-controls"
python3 - "$tmpdir/cost-controls.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("success") is True, payload
data = payload["data"]
assert data.get("ok") is True, data
print(f"  cost gates: {data.get('passed_count')}/{data.get('gate_count')} passed")
PY

get policies "${BACKEND_URL}/policies"
get cases "${BACKEND_URL}/cases?limit=1"
get agents "${BACKEND_URL}/agents"
python3 - "$tmpdir/policies.json" "$tmpdir/cases.json" "$tmpdir/agents.json" <<'PY'
import json, sys
policies, cases, agents = [json.load(open(path, encoding="utf-8")) for path in sys.argv[1:]]
assert policies.get("success") is True and len(policies.get("data", [])) >= 1, policies
assert cases.get("success") is True and len(cases.get("data", {}).get("items", [])) >= 1, cases
assert agents.get("success") is True and len(agents.get("data", [])) >= 5, agents
print(f"  seeded state: policies={len(policies['data'])} cases>=1 agents={len(agents['data'])}")
PY

echo "[check] frontend"
curl --fail --silent --show-error --retry 20 --retry-delay 1 --retry-connrefused \
  "${FRONTEND_URL}" | grep -q "Govern.ai"
echo "  frontend: Govern.ai page served"

echo
echo "Walkthrough gate passed. Open ${FRONTEND_URL} and follow HACKATHON_SUBMISSION.md."
