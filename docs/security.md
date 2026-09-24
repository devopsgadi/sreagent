# Security

Built for a regulated environment. Defaults are conservative.

## The agent can only read

- MCP tools prefixed `action_` are write tools. `mcp_hub.py` removes them from the tool list sent to the LLM,
  and refuses them in the agent loop even if a model asks.
- Writes happen only through `POST /api/runs/{id}/actions`, which needs `ENABLE_ACTIONS=true`,
  an explicit `confirm: true` from the UI dialog, and records actor, params and result in the audit table.
- The rollback action creates a branch and a **Draft** MR. It never merges or deploys.
- In VS Code, Copilot asks for confirmation before running any MCP tool; the `sre-triage` skill also tells it
  not to call `action_*` tools unless asked.

## Data leaving your network

- Every MCP result passes through `common.clean()`: card numbers (Luhn-checked), emails, SSNs,
  bearer tokens and `password=/token=/api_key=` values are masked, strings and lists are truncated.
- Kibana tools return aggregates and a handful of redacted lines, never raw hit dumps.
- Only redacted, truncated tool output reaches the LLM. Use an internal gateway or Azure OpenAI in your
  tenant if data residency matters. Extend `_RULES` in `common.py` for account numbers or customer ids
  specific to your platform.

## Credentials

- Keep them in `.env` or your secret store (Kubernetes Secrets / Azure Key Vault via CSI); never in the repo.
- Each MCP server holds only its own source's credentials; agent-api holds only the LLM key.
- Use least-privilege tokens: read-only for triage; add write scopes only when enabling actions.

## Identity and access

- Put the UI behind oauth2-proxy or your SSO ingress; nginx forwards `X-Forwarded-User`.
- Set `REQUIRE_USER_HEADER=true` so anonymous calls are rejected and every action has a named actor.
- MCP ports in `docker-compose.yml` bind to `127.0.0.1`. In Kubernetes, keep them ClusterIP-only
  and restrict with a NetworkPolicy so only agent-api (and approved dev access) can reach them.

## Before production

- Replace SQLite with Postgres if you run more than one agent-api replica, and Redis pub/sub for SSE fan-out.
- Get the redaction rules and the LLM endpoint reviewed by your security team.
- Consider pinning prompts and the playbook in change control; they decide what evidence the agent collects.
