## Skills (merge this section into the existing AGENTS.md)

Skills live in `.agents/skills/<name>/SKILL.md`, each with a `references/` folder loaded only when a step points to it.

| Skill | Use it when |
|---|---|
| `kibana-k8s-triage` | Gateway errors, 5xx/4xx, Envoy response flags, x-request-id, pod restarts, missing secrets/config, "why is app X failing" |
| `gitlab-change-triage` | Bad deploy, new image tag, "what changed", failed pipeline, which MR caused it, rollback candidate |

Order for an incident: `kibana-k8s-triage` first (where and how it fails), then `gitlab-change-triage` for the service and window it identifies (what changed).

Rules for every skill:
- Read-only. Never call `action_*` tools without explicit human approval in the Anchor UI.
- Always use catalog service names.
- Report evidence with ids (request id, pod, deployment id, SHA, MR iid), never guesses.
