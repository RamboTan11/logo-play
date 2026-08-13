#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_root="$project_root/deploy/runtime/preprod"
private_config="$project_root/backend/config/app.local.preprod.toml"
data_root="$project_root/docker-data/preprod/backend"

mkdir -p "$runtime_root" "$data_root/assets"
printf '%s\n' "$$" >"$runtime_root/runner.pid"

if [[ ! -f "$private_config" ]]; then
  printf 'Missing pre-production private config: %s\n' "$private_config" >&2
  exit 1
fi

cd "$project_root/frontend"
npm run build:real

cd "$project_root"
LOGO_PRIVATE_CONFIG_PATH="$private_config" \
LOGO_RUNTIME_DATA_DIR="$data_root" \
PYTHONPATH="$project_root/backend:$project_root" \
"$project_root/.venv-macos/bin/python" -m uvicorn src.production:create_app --factory --host 127.0.0.1 --port 18099 \
  >"$runtime_root/backend.log" 2>&1 &
backend_pid=$!
printf '%s\n' "$backend_pid" >"$runtime_root/backend.pid"

cleanup() {
  rm -f "$runtime_root/runner.pid" "$runtime_root/frontend.pid" "$runtime_root/backend.pid"
  kill "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT

for attempt in {1..60}; do
  if curl --fail --silent http://127.0.0.1:18099/health >/dev/null; then
    break
  fi
  sleep 0.5
done

if ! curl --fail --silent http://127.0.0.1:18099/health >/dev/null; then
  cat "$runtime_root/backend.log" >&2
  exit 1
fi

cd "$project_root/frontend"
VITE_USE_MOCK=false VITE_BACKEND_PROXY_TARGET=http://127.0.0.1:18099 \
  npm run dev -- --host 127.0.0.1 --port 15175 \
  >"$runtime_root/frontend.log" 2>&1 &
frontend_pid=$!
printf '%s\n' "$frontend_pid" >"$runtime_root/frontend.pid"

wait "$frontend_pid"
