#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_root="$project_root/deploy/runtime/preprod"

if [[ -f "$runtime_root/runner.pid" ]]; then
  runner_pid="$(cat "$runtime_root/runner.pid")"
  kill "$runner_pid" 2>/dev/null || true
fi

for process_name in frontend backend; do
  pid_file="$runtime_root/$process_name.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    kill "$pid" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    rm -f "$pid_file"
  fi
done
rm -f "$runtime_root/runner.pid"
