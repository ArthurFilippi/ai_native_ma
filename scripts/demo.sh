#!/usr/bin/env bash
# Reproducible demo: fixed seed, offline mock provider, no keys, no network after install.
# Starts the API on :8000 and the web client on :3000. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m ainma.demo prepare
python -m ainma.demo script

if [ ! -d web/node_modules ]; then
  (cd web && npm ci)
fi

python -m ainma.api --port 8000 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

# Wait for the API before opening the client.
for _ in $(seq 1 50); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then break; fi
  sleep 0.2
done

(cd web && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev)
