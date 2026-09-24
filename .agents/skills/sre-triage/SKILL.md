---
name: sre-triage
description: Triage a ServiceNow incident end to end using the servicenow, datadog, kibana and gitlab MCP servers, and produce an evidence-backed RCA draft. Use when asked to triage, investigate, or find the cause of an INC number.
---

# SRE triage

Same playbook the web agent uses (`agent_api/app/prompts.py`). Keep them in sync.

1. `servicenow.get_incident(number)`: note `service`, CI, opened time.
2. In parallel: `datadog.get_active_monitors(service)`, `datadog.query_metric(service, "error_rate", 120)`.
3. In parallel: `kibana.error_histogram(service, 120)` for onset, `kibana.top_error_signatures(service, 60)` for mechanism.
4. In parallel: `gitlab.list_deployments(service, 24)`, `servicenow.list_changes(service, 24)`.
5. If a deploy precedes onset: `gitlab.get_merge_request_changes(service, mr_iid)`.
6. Optional: `servicenow.related_incidents(service)` for recurrence.

Output, in this order:
- **Summary** (2 sentences) and **confidence** (high = change aligns with onset AND logs show mechanism; medium = one; low = neither)
- **Timeline** (UTC, one line per event, tagged with source)
- **Evidence** (one sentence each, with MR link / change / monitor id)
- **Recommended next steps**, then **open questions**

Never call `action_add_work_note` or `action_create_rollback_mr` unless the user explicitly says to.
