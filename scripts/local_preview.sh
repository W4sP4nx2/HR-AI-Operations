#!/usr/bin/env bash
set -euo pipefail

# Zero-spend local preview for the HR AI Command Center.
# Starts FastAPI + Next.js with deterministic fallback mode enabled, Fireworks
# routing configured but live calls gated until a key is supplied.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3001}"
HOST="${HOST:-127.0.0.1}"

BACKEND_URL="http://${HOST}:${BACKEND_PORT}"
FRONTEND_URL="http://${HOST}:${FRONTEND_PORT}"

if [ ! -d "${ROOT_DIR}/frontend/node_modules" ]; then
  echo "frontend/node_modules not found. Run: cd frontend && npm install"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found"
  exit 1
fi

echo "Seeding deterministic local demo data and vectors"
(
  cd "${ROOT_DIR}/backend"
  AUTH_ENFORCE=false \
  MOCK_LLM=true \
  DEMO_MODE=true \
  LLM_PROVIDER=fireworks \
  EMBEDDING_PROVIDER=hashing \
  python3 -m scripts.seed_data
)

cleanup() {
  if [ -n "${BACKEND_PID:-}" ] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Starting zero-spend backend on ${BACKEND_URL}"
(
  cd "${ROOT_DIR}/backend"
  AUTH_ENFORCE=false \
  MOCK_LLM=true \
  DEMO_MODE=true \
  LLM_PROVIDER=fireworks \
  EMBEDDING_PROVIDER=hashing \
  FIREWORKS_BASE_URL="${FIREWORKS_BASE_URL:-https://api.fireworks.ai/inference/v1}" \
  ALLOWED_MODELS="${ALLOWED_MODELS:-accounts/fireworks/models/gemma-3-27b-it,accounts/fireworks/models/llama-v3p1-8b-instruct}" \
  python3 -m uvicorn api.main:app --host "${HOST}" --port "${BACKEND_PORT}"
) &
BACKEND_PID=$!

echo "Starting frontend on ${FRONTEND_URL}"
(
  cd "${ROOT_DIR}/frontend"
  NEXT_PUBLIC_API_BASE="${BACKEND_URL}" \
  NEXT_PUBLIC_WS_URL="ws://${HOST}:${BACKEND_PORT}/ws/feed" \
  npm run dev -- --hostname "${HOST}" --port "${FRONTEND_PORT}"
) &
FRONTEND_PID=$!

echo ""
echo "Local preview:"
echo "  App:      ${FRONTEND_URL}"
echo "  Backend:  ${BACKEND_URL}"
echo "  Evidence: ${BACKEND_URL}/lifecycle/capabilities"
echo ""
echo "Open Analytics -> Dynamic Capability Engine."
echo "Fireworks and AMD/Gemma should show live_gated until keys/runtime evidence are provided."
echo "Press Ctrl+C to stop both servers."

wait
