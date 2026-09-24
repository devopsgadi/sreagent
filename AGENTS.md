# AGENTS.md

This repo ships the SRE triage agent in two front ends that share one set of MCP servers:

- **Web UI** (`ui/` + `agent_api/`): for on-call, managers, anyone outside VS Code.
- **Copilot Chat in VS Code**: for engineers. `.vscode/mcp.json` points at the same servers;
  the playbook below lives in `.agents/skills/sre-triage/SKILL.md`.

## Rules for any agent working in this repo
- MCP tools named `action_*` write to ServiceNow or GitLab. Never call them without explicit human approval.
- Tool results are already redacted and truncated server-side. Do not ask for raw log dumps.
- Services are resolved through `config/services.yaml`. Use service names, never raw project ids or index patterns.
- Code changes: Python 3.11+, keep MCP tools small and single-purpose; add mocks in `mcp_servers/sre_mcp/mocks.py`
  for every new tool so demo mode keeps working.
