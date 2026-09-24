# SRE agent

Triages a ServiceNow incident by pulling evidence from ServiceNow, Datadog, Kibana/Elastic and GitLab
through MCP servers, then drafts an RCA. Engineers can post it back to the ticket or open a draft rollback MR.

One set of MCP servers backs two front ends:

- **Web UI** for on-call and managers: live triage progress, correlated timeline, RCA with actions.
- **Copilot Chat in VS Code** for engineers: `.vscode/mcp.json` plus the `sre-triage` skill.

```
Browser (React) ──SSE──> agent-api (FastAPI) ──> LLM (Azure OpenAI / internal gateway / Anthropic)
                              │ MCP client
                              ├── servicenow-mcp :8101
                              ├── datadog-mcp    :8102      <── VS Code Copilot Chat
                              ├── kibana-mcp     :8103          (same servers)
                              └── gitlab-mcp     :8104
```

## Quick start (demo mode, no credentials)

```bash
cp .env.example .env
docker compose up --build
# UI:  http://localhost:3000     API docs: http://localhost:8080/docs
```

Pick INC0048213 and run triage. Mock data plays a bad-deploy scenario end to end.

Without Docker:

```bash
make install && make dev      # UI on :5173
make test                     # unit tests
make smoke                    # end-to-end check against a running stack
```

## Going live

1. In `.env`: set `MOCK=false`, set `LLM_PROVIDER` (`azure`, `openai` or `anthropic`) and its `LLM_*` values, and fill in credentials for each source.
2. Edit `config/services.yaml` so every service maps to its SNOW CI, GitLab project, ES index and Datadog service.
3. Put the UI behind your SSO proxy, set `REQUIRE_USER_HEADER=true`, and turn on `ENABLE_ACTIONS=true` when you're ready for write actions.
4. Optional: point a ServiceNow Business Rule at `POST /api/webhooks/servicenow` for auto-triage (see docs).

## Docs

- [Configuration](docs/configuration.md): every env var, service map, LLM providers, webhook
- [Security](docs/security.md): read-only agent, gated writes, redaction, credentials, audit
- [Extending](docs/extending.md): add a tool, add a source (Kubernetes, Azure), tune the playbook

## Layout

| Path | What |
|---|---|
| `mcp_servers/sre_mcp/` | One module per source, plus `common.py` (redaction, service map) and `mocks.py` |
| `agent_api/app/` | `mcp_hub.py` MCP client, `llm.py` providers, `agent.py` loop, `store.py` SQLite + events, `main.py` routes |
| `ui/src/` | React app; `hooks/useTriageStream.js` turns the SSE stream into UI state |
| `config/services.yaml` | Service map shared by all MCP servers |
| `.vscode/mcp.json`, `AGENTS.md`, `.agents/skills/` | Copilot Chat integration |

Note: `mcp` is pinned to `<2`; the 2.x SDK renamed FastMCP and changed the client API.
