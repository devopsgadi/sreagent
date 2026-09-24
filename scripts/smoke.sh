#!/usr/bin/env bash
# Triage one incident through the running stack and print the result.
set -euo pipefail
API="${API:-http://localhost:8080}"
INC="${1:-INC0048213}"

echo "== health"
curl -fsS "$API/api/health"; echo

echo "== sources"
curl -fsS "$API/api/sources" | python3 -c '
import sys, json
for name, s in json.load(sys.stdin).items():
    state = "ok" if s["ok"] else "DOWN " + str(s["error"])
    print("  %s: %s (%d tools)" % (name, state, len(s["tools"])))
'

echo "== triage $INC"
RID=$(curl -fsS -XPOST "$API/api/triage" -H 'content-type: application/json' \
  -d "{\"incident\":\"$INC\"}" | python3 -c 'import sys, json; print(json.load(sys.stdin)["run_id"])')
curl -sN --max-time 180 "$API/api/runs/$RID/events" | sed -n 's/^event: /  /p'

curl -fsS "$API/api/runs/$RID" | python3 -c '
import sys, json
r = json.load(sys.stdin)
rca = r.get("rca") or {}
print("== status", r["status"])
print("  confidence:", rca.get("confidence"))
print("  summary:", rca.get("summary"))
if r.get("error"):
    print("  error:", r["error"])
'
