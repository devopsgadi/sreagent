# Extending

## Add a tool to an existing source

1. Add a function with `@mcp.tool()` in `mcp_servers/sre_mcp/<source>.py`. The docstring is what the LLM
   reads, so say what it returns and when to use it.
2. Take `service: str` and resolve it with `resolve_service()`. Return `clean(...)` output.
3. Add fixture data in `mocks.py` so demo mode keeps working.
4. If the playbook should use it, mention it in `agent_api/app/prompts.py` and `.agents/skills/sre-triage/SKILL.md`.

Name write tools `action_*`; they are then hidden from the agent and only callable via the actions API.

## Add a new source (e.g. Kubernetes, Azure)

1. Create `mcp_servers/sre_mcp/kubernetes.py` with a `FastMCP("kubernetes")` instance and
   `if __name__ == "__main__": run(mcp, 8105)`.
   Suggested read tools: `pod_status(service)`, `recent_events(service)`, `rollout_history(service)`.
   Azure: `resource_health(service)`, `activity_log(service, hours)`.
2. Add fields to `services.yaml` (namespace, deployment, resource ids).
3. Add a service to `docker-compose.yml` and `KUBERNETES_MCP_URL` to `agent_api/app/config.py` `mcp_servers`.
4. UI: add `{ key: "kubernetes", label: "Kubernetes", role: "Pods and rollouts" }` to `SOURCES` in `ui/src/api.js`
   and a colour in `styles.css` (`--c-kubernetes` and `.src-kubernetes`). Lanes, timeline and feed pick it up.
5. Add it to `.vscode/mcp.json`.

## Tune the agent

- Playbook and RCA contract: `agent_api/app/prompts.py`. Keep the JSON keys; the UI and actions depend on them.
- Step budget and result size: `AGENT_MAX_STEPS`, `TOOL_RESULT_MAX_CHARS`.
- Add an action: new branch in `run_action()` in `main.py`, a matching `action_*` MCP tool, and an entry in
  `ACTIONS` in `ui/src/components/RcaPanel.jsx`.
