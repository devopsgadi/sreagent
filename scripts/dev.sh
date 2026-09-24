#!/usr/bin/env bash
# Run MCP servers, agent-api and the UI dev server locally. Ctrl+C stops everything.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
set -a; [ -f "$ROOT/.env" ] && . "$ROOT/.env"; set +a
export SERVICE_MAP_PATH="$ROOT/config/services.yaml" DB_PATH="${DB_PATH:-$ROOT/sre_agent.db}"

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

cd "$ROOT/mcp_servers"
for s in servicenow:8101 datadog:8102 kibana:8103 gitlab:8104; do
  "$PY" -m "sre_mcp.${s%%:*}" --transport http --port "${s##*:}" & pids+=($!)
done
cd "$ROOT/agent_api"
"$PY" -m uvicorn app.main:app --port 8080 --reload & pids+=($!)
cd "$ROOT/ui"
npx vite --port 5173 & pids+=($!)

echo "UI: http://localhost:5173   API: http://localhost:8080/docs"
wait
