---
name: kibana-k8s-triage
description: Kibana-only, end-to-end incident triage for Kubernetes/Istio workloads (on-prem and AKS) with NO cluster access. From namespace, app and incident time it localizes the failing hop (edge → gateway → sidecar → app → dependency), classifies the cause from log signatures (Envoy flags and response_code_details, TLS/certs, Kafka, Cassandra, databases, Spring Boot, Key Vault/identity, micro-frontends), infers pod restarts, OOM, probe failures and deploys from logs alone, diffs against a baseline window, and returns an evidence-backed RCA. Use whenever an incident, ServiceNow ticket or user mentions gateway errors, 5xx/4xx, timeouts, latency, Kibana/Elastic logs, istio-proxy, Envoy flags, x-request-id, certificates/SSL/PKIX, Kafka lag/rebalance, Cassandra timeouts, Hikari, pod restarts, secret not found, canary, or asks "why is app X failing" — even if Kibana is not named.
---

# Kibana-Only K8s / Istio Incident Triage Engine

The agent has **no kubectl, no exec, no cluster API, no Azure portal**. Kibana / Elasticsearch is the only source of truth. Every conclusion must be derived from log documents, and every gap must be named as a gap, not papered over with a guess.

## Tools

Prefer `kibana` MCP tools when present (catalog service names always):

| Step | MCP tool | Fallback |
|---|---|---|
| 0 Discover | `discover_fields`, `list_indices` | `references/field-mapping.md` |
| 1 Scope / blast radius | `gateway_errors`, `error_heatmap` | `references/es-dsl.md` §Scope |
| 2 Trace | `trace_lookup` | §Trace |
| 3 Hop + flags | `sidecar_inbound_errors`, `istio_outbound_failures` | §Gateway, §Outbound |
| 4 Signatures | `signature_scan`, `config_secret_signatures` | `references/signature-catalog.md` |
| 5 Diff vs baseline | `baseline_diff`, `log_patterns` | §Baseline diff, §Patterns |
| 6 Pod / deploy | `pod_lifecycle`, `k8s_warning_events` | `references/k8s-from-logs.md` |
| 7 Empty results | `sanity_checks` | Step 7 below |

If a tool is missing, run the DSL / ES|QL from `references/es-dsl.md` via the raw search tool. Proposed new MCP tools are specified in `references/mcp-tool-spec.md`.

Use the service **catalog** (not guesses) to resolve: app → namespace, K8s Service name, ports, owned dependencies (Kafka topics, Cassandra keyspaces, DBs, downstream APIs, Apigee proxy, mainframe/Hogan routes), and cross-namespace callers.

## Hard rules

1. **Read-only, Kibana-only.** Never propose kubectl/az/istioctl as a step the agent runs. Things only the cluster can confirm go into `Escalation asks` for the platform team.
2. **Labels, never one pod name.** Pods are replaced; dead-pod logs stay in Elastic and must be included.
3. **Absolute UTC window.** Convert the ticket's timezone explicitly (Pacific: PDT = UTC−7, PST = UTC−8; IST = UTC+5:30) and state the conversion.
4. **Verify fields first** (Step 0). Never assume ECS names.
5. **Evidence, not guesses.** Every claim cites the query and 1–3 sample lines (timestamp, pod, request id / trace id).
6. **Baseline before blame.** An error that also occurs at the same rate in the baseline window is noise, not the cause.
7. **Earliest anomaly wins.** The root cause is the first new signal in the timeline, usually upstream of the loudest one.
8. **Bounded queries.** Always `size`, a time range, and aggregations instead of pulling raw docs. Never page more than 500 docs.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `NS` | yes | From ticket or catalog |
| `APP` | yes | `app` label value (fallback `app.kubernetes.io/name`, deployment name prefix) |
| `INCIDENT_TIME` | yes | Convert to UTC |
| `ENV` / cluster | derive | IT, UAT, pre-prod, EN, EMP, PROD; PCI vs non-PCI. Pick index pattern and cluster filter accordingly |
| `SVC` | derive | K8s Service name from catalog; often = APP |
| `ERROR` | optional | 502, 504, "timeout", "cert", "kafka lag", "secret missing" |
| `REQUEST_ID` / `TRACE_ID` | optional | `x-request-id`, `traceId`, Akamai reference, Apigee messageid |
| `HOST` / `PATH` | optional | Public host + path users hit |
| `GW_NS` / `GW_APP` | default | `istio-system` / `istio-ingressgateway`; confirm per env |

Windows: **incident** = `T−15m … T+15m`; **baseline** = same window 24h earlier (and 7d earlier on Mondays/after weekends). Widen to ±2h if empty or if the ticket was raised long after impact began.

## Step 0 — Discover fields and log shape

1. Fetch 1 newest doc for `NS`/`APP` from app container and 1 from `istio-proxy`; map onto placeholders below (`references/field-mapping.md`).
2. Record: Istio access log JSON or TEXT; app logs JSON (logstash encoder) or plain; whether `traceId`/`spanId` exist; whether a K8s events index exists; whether edge (NGINX Plus/F5/Apigee) logs are indexed.
3. If Envoy fields are text-only, parse at query time with **ES|QL `DISSECT`** or `runtime_mappings` + grok (`references/es-dsl.md` §Text access logs). Flag "ingest pipeline needed" as a gap, but do not stop.

Placeholders: `{ns} {app} {pod} {container} {image} {node} {level} {msg} {logger} {trace} {cluster}` + Envoy fields `response_code response_flags response_code_details upstream_cluster upstream_host upstream_transport_failure_reason connection_termination_details authority path method x_request_id duration upstream_service_time bytes_sent bytes_received downstream_remote_address requested_server_name`.

```
BASE      = {ns} : "NS" and {app} : "APP"
APP_LOGS  = BASE and not {container} : "istio-proxy"
SIDECAR   = BASE and {container} : "istio-proxy"
GATEWAY   = {ns} : "GW_NS" and {app} : "GW_APP"
SVC_MATCH = upstream_cluster : *|SVC.NS.svc.cluster.local
INBOUND   = SIDECAR and upstream_cluster : inbound*
OUTBOUND  = SIDECAR and upstream_cluster : outbound*
```

Canary / subsets: `upstream_cluster` = `outbound|PORT|SUBSET|host`. Always split by SUBSET (`stable` vs `next`, `v1` vs `v2`) and by `version` label in app logs. An error isolated to one subset is a release defect, not a platform issue.

## Step 1 — Scope and blast radius (always first)

Run three aggregations over the incident window, each also over baseline:

1. **Gateway**: `GATEWAY and response_code >= 400` → terms `upstream_cluster` × `response_code` × `response_flags` × `response_code_details`, date_histogram 1m.
2. **Namespace**: `{ns} : "NS" and (level ERROR or response_code >= 500)` → terms `{app}`.
3. **Cluster-wide**: `response_code >= 500` across all namespaces → terms `{ns}`.

Classify blast radius:

| Pattern | Points to |
|---|---|
| One app, one subset | Release defect / canary |
| One app, all pods | App, its config/secret, or its dependency |
| Many apps sharing one dependency | That dependency (DB, Kafka, Cassandra, mainframe, Apigee target) |
| Many apps across namespaces, same node(s) | Node / network (group by `{node}`) |
| Everything behind the gateway | Gateway, certs, edge, istiod, DNS |
| Gateway clean, users see errors | Failure upstream of Istio (Akamai / F5 / NGINX Plus / Apigee) → `references/playbooks/edge-and-apigee.md` |

Collect: counts by code × flag × details, top paths, first-seen / last-seen (ongoing?), 3 sample request ids, error rate vs baseline.

## Step 2 — Trace one request end to end

`x_request_id : "REQUEST_ID"` over ±1h, sorted by `@timestamp`. Last hop that logged is where it broke:

| Seen in | Not seen in | Conclusion |
|---|---|---|
| edge only | gateway | Edge / Apigee / LB; or host/SNI not on gateway |
| gateway | app sidecar | Never reached pod: NR / UH / UF / mTLS / NC. Use gateway flags |
| app sidecar inbound | app container | Sidecar → app failed: app down, wrong port, crashed, slow start |
| app container | — | App handled it; read its errors and outbound calls |
| app sidecar outbound 5xx/0 | — | Dependency failure; name it from `upstream_cluster` / `authority` |

**Bridging to app logs** when the app doesn't log `x-request-id`: take the inbound sidecar line (pod P, time t, path) and query `APP_LOGS and {pod}:P` in `[t − duration − 1s, t + 1s]`. A `traceId` found there links all downstream app logs. Prefer `traceId` thereafter.

## Step 3 — Read the Envoy verdict

Decode `response_code` + `response_flags` + `response_code_details` + `upstream_transport_failure_reason` with `references/envoy-response-flags.md`. `response_code_details` is the most precise field; always aggregate on it. Highlights:

| Signal | Meaning |
|---|---|
| 502/503 `UF` + `TLS_error` | mTLS/TLS failure to upstream → `playbooks/tls-certs.md` |
| 503 `UH` `no_healthy_upstream` | 0 ready endpoints or all outlier-ejected → `k8s-from-logs.md` |
| 503 `UO` `overflow` | DestinationRule connectionPool / circuit breaker |
| 503 `UC` `connection_termination` | Keepalive mismatch / app crash mid-request |
| 504 `UT` `upstream_response_timeout` | App or its dependency slow; check `upstream_service_time` |
| 404 `NR` `route_not_found` | VirtualService / Gateway host or path mismatch |
| 403 `rbac_access_denied_matched_policy[...]` | AuthorizationPolicy, not the app |
| 401/403 `jwt_authn_access_denied{...}` / `ext_authz_*` | RequestAuthentication / external auth |
| 502 `BlackHoleCluster` | REGISTRY_ONLY egress, missing ServiceEntry |
| `response_code: 0` + `DC` | Client gave up before Envoy answered (client/LB timeout shorter than request) |

Then `playbooks/envoy-istio.md` for filters, retries, outlier detection, timeouts, rate limits, Lua/Wasm, and istio-proxy (xDS/NACK/SDS) health.

## Step 4 — Dependency map and signature scan

1. **Outbound map**: `OUTBOUND` → terms `upstream_cluster` (or `authority`) × `response_code` × `response_flags`, plus p95 `duration`. TCP dependencies (Kafka 9092/9093, Cassandra 9042, Postgres 5432, Oracle 1521, SQL Server 1433, Redis 6379/6380, MQ 1414) appear with `response_code 0`: judge them by flags, `bytes_sent`, and `duration`, not by code. `PassthroughCluster` + IP = destination outside the mesh registry; resolve the IP via catalog.
2. **Signature scan** over `APP_LOGS` (incident vs baseline) using `references/signature-catalog.md`: one query with a `filters` aggregation, one bucket per signature. Report only signatures that are new or grew ≥3× vs baseline.
3. Route to the matching playbook:

| Signature family | Playbook |
|---|---|
| TLS, PKIX, handshake, certificate, SDS | `playbooks/tls-certs.md` |
| Kafka client / Spring Kafka / Event Hubs | `playbooks/kafka.md` |
| Cassandra / DataStax driver | `playbooks/cassandra.md` |
| Hikari, JDBC, Redis, MQ, mainframe/Hogan, HTTP clients, resilience4j, OOM, startup, Key Vault, AAD | `playbooks/springboot.md` |
| React micro-frontends, static assets, CORS, remoteEntry, NGINX in pod | `playbooks/microapps-frontend.md` |
| Akamai, F5, NGINX Plus, Apigee | `playbooks/edge-and-apigee.md` |

Cross-namespace dependency failing → recurse this skill on that service (max depth 3; stop at a shared dependency many callers fail against).

## Step 5 — Baseline diff and unknown-error discovery

When signatures don't explain it, find **what is new**:

- `significant_text` / `significant_terms` on `{msg}` or `{logger}` with the incident window as foreground and baseline as background (`es-dsl.md` §Baseline diff).
- `categorize_text` aggregation (ES 8.x) or ES|QL `CATEGORIZE` (8.18+/9.x) to collapse thousands of lines into patterns; compare pattern counts vs baseline.
- Exception class histogram: extract `stack_trace` first line / `exception.class` and rank by growth.

Any new pattern that starts before the first user-facing error is the prime suspect.

## Step 6 — Pod lifecycle, restarts, deploys (always run)

Kibana-only inference, detailed in `references/k8s-from-logs.md`:

- Aggregate `BASE` per `{pod}`: `{image}`, min/max `@timestamp`, `{node}`.
- **ReplicaSet hash** = middle token of `app-<rs-hash>-<pod-suffix>`. A new RS hash = a new rollout, even with an unchanged image (ConfigMap/secret/env change).
- **New image tag** starting just before errors → likely bad deploy. Report old → new tag, time, subset.
- **Container restart** without pod replacement: repeated Spring Boot banner / `Starting ...Application` in the same pod name.
- **OOMKill / SIGKILL**: logs stop abruptly with no `Commencing graceful shutdown`, followed by a restart in the same pod. **Graceful**: `Commencing graceful shutdown` / `Shutdown completed` = normal SIGTERM (scale-down, rollout, eviction, node drain).
- **Probe failures**: istio-proxy/pilot-agent lines for `/app-health/<container>/readyz|livez`, `Envoy proxy is NOT ready`, slow `Started X in N seconds` vs probe delay.
- **Node issue**: several pods on the same `{node}` stop at the same minute.
- Hand image-tag/RS changes to `gitlab-change-triage` for commit/MR/pipeline.

## Step 7 — Empty-result sanity checks

1. Do other apps have logs in the window? If not: shipper outage, index rollover gap, or outside retention. Report it.
2. Re-check timezone conversion and index pattern (PCI vs non-PCI, env-specific cluster).
3. Label wrong? Retry `{pod} : APP-*`, `app.kubernetes.io/name`, or container name.
4. No istio-proxy docs at all → access logging disabled or sidecar not injected (ambient/no mesh). Gap; escalation ask.
5. Logs present but truncated multiline stack traces → parsing gap; search by exception class only.

## Confidence scoring

| Level | Requires |
|---|---|
| High | Failing hop localized by trace + matching signature + timeline (signal starts before/with errors) + absent in baseline |
| Medium | Two of the above |
| Low | Correlation only, or key data missing (no access logs, no events, unparsed logs) |

Always list the alternative hypothesis you ruled out and the query that ruled it out.

## Output format

```
Incident: <ticket>  | Env/cluster: <env, PCI?>  | NS/APP: <ns>/<app>
Window (UTC): <from> – <to>   (ticket <tz> → UTC conversion stated)
Baseline: <window>   Field mapping: <placeholders → fields>; access logs <JSON|TEXT>

Blast radius: <one subset | one app | apps sharing X | node | all gateway | pre-mesh>
Symptom:      <codes × flags × details, count, rate vs baseline, top paths, first/last seen>
Timeline:     <T0 first anomaly> → <T1 first user error> → <T2 peak> → <T3 recovery/ongoing>
Failing hop:  <edge | gateway | sidecar→app | app | dependency X | pod never started>
Evidence:     <query> → <1-3 sample lines: ts, pod, request/trace id, message>
Pods/deploy:  <pods in window, restarts, OOM/graceful, RS hash / image tag change at T, subset>
Likely cause: <one sentence>   Confidence: <high|medium|low>
Ruled out:    <hypothesis → query that disproved it>
Gaps:         <no events index, unparsed access logs, no traceId, retention, shipper outage>
Escalation asks (platform team, read-only): <what only cluster/Azure access can confirm>
Recurse:      <dependency service handed to this skill / gitlab-change-triage>
```

## References

- `references/field-mapping.md` — field variants, text access-log positions, canary subset parsing.
- `references/envoy-response-flags.md` — flags, `response_code_details`, transport failure reasons, termination details.
- `references/signature-catalog.md` — master KQL signature table by family, with cause and playbook.
- `references/es-dsl.md` — DSL / ES|QL for every step, including text-log parsing, baseline diff, log patterns.
- `references/k8s-from-logs.md` — inferring pods, restarts, OOM, probes, rollouts, HPA, nodes without cluster access.
- `references/playbooks/` — `envoy-istio`, `tls-certs`, `kafka`, `cassandra`, `springboot`, `microapps-frontend`, `edge-and-apigee`.
- `references/mcp-tool-spec.md` — tool contracts for the `kibana` MCP server.
- Related skill: `gitlab-change-triage`.
