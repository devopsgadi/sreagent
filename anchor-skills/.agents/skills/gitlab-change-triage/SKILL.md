---
name: gitlab-change-triage
description: Find what changed before an incident using GitLab, read-only. Lists deployments to an environment in a time window, maps a container image tag to its commit and merge requests, reads MR diffs and approvals, compares a good and a bad ref, and finds failed pipelines and the failing job log lines. Use this skill whenever an incident, ServiceNow ticket or another skill mentions a bad deploy, new image tag, recent release, rollback candidate, "what changed", a failed pipeline, or asks which MR caused a problem — even if GitLab is not named explicitly.
---

# GitLab change triage

Answer one question with evidence: **what changed for this service just before the incident, and who approved it?** Read-only. Never fix anything.

## Tools

If the `gitlab` MCP server is available, use its tools instead of raw API calls: `list_deployments`, `image_tag_to_commit`, `get_merge_request_changes`, `compare_refs`, `list_failed_pipelines`, `variable_names`. Always pass catalog service names; the catalog supplies the project and environment. Fall back to the endpoints in `references/gitlab-api.md` only when no MCP tool covers the step.

## Hard rules

- **Read-only.** Never call POST/PUT/DELETE endpoints: no pipeline retry, job play, MR merge, variable changes. The only write in this system is the separately approved `action_create_rollback_mr`, which this skill never calls.
- **Never output variable values.** `variables` endpoints return values; keep names only.
- **Job logs: tail only** (last ~100 lines around the failure), and redact secrets before quoting.
- **Pin an absolute UTC window** from the incident time and state the timezone conversion.
- **Evidence, not guesses.** Every conclusion cites a deployment id, SHA, MR iid or job id.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `SERVICE` | yes | Catalog name; resolves to the GitLab project and environment |
| `INCIDENT_TIME` | yes | Convert to UTC |
| `ENV` | derive | From the catalog (`gitlab_environment`) |
| `OLD_TAG` / `NEW_TAG` | optional | From the kibana-k8s-triage Step 6 pod lifecycle |
| `GOOD_REF` / `BAD_REF` | optional | When known |

Default window: `INCIDENT_TIME - 24h` to `INCIDENT_TIME`. Narrow to the 2 hours before onset when ranking candidates.

## Workflow

### Step 1 — Locate the project
Use the catalog's `gitlab_project`. Only if missing, search projects by name (`references/gitlab-api.md` §1) and report the catalog gap.

### Step 2 — Deployments in the window
List deployments to `ENV` in the window, newest first. For each: id, SHA, finished time, deployable job, and the MRs included (commit → MRs). Mark the **last deploy before onset** as the prime candidate.

### Step 3 — Image tag → commit (when tags are known)
Try in order: short SHA in the tag → pipeline id in the tag → build job trace (`docker push`, `crane push`, `IMAGE_TAG=`) → registry tag `created_at`. Report which strategy matched.

### Step 4 — What the change did
For the candidate: MR diffs (focus on config, Helm values, dependencies, connection/timeout/TLS settings, feature flags), MR approvals, and `compare GOOD → BAD` when two refs are known. Summarise the risky hunks in one line each; do not paste whole diffs.

### Step 5 — Pipelines
Failed pipelines and jobs in the window, including downstream/child pipelines. Quote only the failing lines from the job log tail.

### Step 6 — Config changes (names only)
Changed CI/CD variable **names** and, where available, audit events (who changed what, when).

### Step 7 — Rank and stop
- **Strong:** a deploy within 30 min before onset whose diff touches the failing area seen in logs.
- **Weak:** a deploy in the window with unrelated changes.
- **None:** no deploys, merges or failed pipelines in the window — say so; that rules out "bad deploy".

## Output format

```
Service: <svc> | Project: <path> | Env: <env> | Window (UTC): <from> – <to>
Deploys:      <id · sha · finished · MRs> (newest first; prime candidate marked)
Tag → commit: <old tag → new tag → sha (strategy)>
Change:       <MR !iid title · author · approvers · risky hunks (1 line each)>
Pipelines:    <failed pipeline/job ids + failing lines>
Config:       <changed variable names / audit events>
Verdict:      <strong | weak | none> — <one sentence>
Rollback candidate: <MR !iid or none>   (proposal only; requires human approval)
Gaps:         <no audit events (non-Premium), tag strategy failed, etc.>
```

## References

- `references/gitlab-api.md`: read-only endpoints, pagination, tag → commit strategies, safety list.
- Related skill: `kibana-k8s-triage` — which pods and tags changed, and how the failure looks in logs.
