# Configuration

All settings come from `.env` (see `.env.example`). Docker Compose passes it to every container.

## Modes

| Var | Default | Meaning |
|---|---|---|
| `MOCK` | `true` | MCP servers return fixture data instead of calling real APIs |
| `LLM_PROVIDER` | `mock` | `mock`, `openai` (any OpenAI-compatible gateway), `azure`, `anthropic` |
| `MOCK_STEP_DELAY` | `1.2` | Seconds per step in mock LLM mode, so the live UI is watchable |

You can mix modes: real MCP data with `LLM_PROVIDER=mock` is a quick way to check connectivity,
though the mock LLM only follows the fixed playbook.

## LLM

| Provider | URL called | Auth |
|---|---|---|
| `openai` | `{LLM_BASE_URL}/chat/completions` | `Authorization: Bearer {LLM_API_KEY}` |
| `azure` | `{LLM_BASE_URL}/openai/deployments/{LLM_MODEL}/chat/completions?api-version={AZURE_API_VERSION}` | `api-key` header |
| `anthropic` | `{LLM_BASE_URL}/v1/messages` | `x-api-key` |

The model must support tool/function calling. `LLM_TIMEOUT`, `LLM_MAX_TOKENS` tune requests.
`CA_BUNDLE` points at a corporate CA file for internal endpoints (used by the MCP servers and the LLM client).

## Agent

| Var | Default | Meaning |
|---|---|---|
| `AGENT_MAX_STEPS` | `10` | Tool-calling rounds before the agent is forced to answer |
| `TOOL_RESULT_MAX_CHARS` | `6000` | Per-tool-result cap sent to the LLM |
| `ENABLE_ACTIONS` | `false` | Allow work note / rollback MR from the UI |
| `REQUIRE_USER_HEADER` | `false` | Reject API calls without `X-Forwarded-User` |
| `DB_PATH` | `./sre_agent.db` | SQLite file for runs, events, audit |
| `*_MCP_URL` | `http://localhost:810x/mcp` | Where agent-api finds each MCP server |

## Sources

- **ServiceNow**: `SNOW_URL`, then `SNOW_TOKEN` (OAuth bearer) or `SNOW_USER` + `SNOW_PASSWORD`. Needs read on `incident`, `change_request`; write on `incident.work_notes` for the action.
- **Datadog**: `DD_SITE`, `DD_API_KEY`, `DD_APP_KEY` (application key scoped to monitors_read, metrics_read, events_read). Metric templates in `datadog.py` assume APM `trace.http.request.*` metrics; adjust `METRICS` to your naming.
- **Elastic**: `ES_URL`, `ES_API_KEY` (or user/password), `KIBANA_URL` for Discover links. Field names: `ES_LEVEL_FIELD`, `ES_ERROR_TYPE_FIELD`, `ES_MESSAGE_FIELD`. The service field and index come from `services.yaml`.
- **GitLab**: `GITLAB_URL`, `GITLAB_TOKEN` (`read_api`; `api` only if rollback MRs are enabled).

## Service map (`config/services.yaml`)

Every tool takes a `service` name and resolves it here, so the LLM never sees project ids or index patterns.
Aliases match on key, `snow_ci`, `datadog_service` or `display_name`. ServiceNow incidents are mapped
to a service through their `cmdb_ci`.

## ServiceNow webhook

`POST /api/webhooks/servicenow` with header `X-Webhook-Secret: {WEBHOOK_SECRET}` and body
`{"number": "INC...", "priority": "2"}`. Runs triage when the priority's first digit is in
`AUTO_TRIAGE_PRIORITIES` (default `1,2`). Trigger it from a Business Rule (after insert on incident)
or a Flow Designer REST step.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/health` | mode, actions flag |
| GET | `/api/sources` | per-server reachability and tools |
| GET | `/api/incidents` | open incidents + latest run per incident |
| POST | `/api/triage` | `{"incident": "INC..."}` → `run_id` |
| GET | `/api/runs/{id}/events` | SSE stream (replays history, supports `Last-Event-ID`) |
| GET | `/api/runs/{id}` | run with RCA |
| POST | `/api/runs/{id}/actions` | `{"action": "post_work_note" or "draft_rollback_mr", "confirm": true}` |
| GET | `/api/audit` | action audit log |
