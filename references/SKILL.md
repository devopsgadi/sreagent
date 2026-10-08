---
name: kibana-k8s-triage
description: Triage Kubernetes/Istio application incidents from Kibana logs using only namespace, app name, and incident time. Builds KQL and Elasticsearch queries to find gateway errors (502/503/504/404), trace a request across gateway → sidecar → app → dependencies, list the endpoints an app calls, detect missing secrets/config, find crashed or replaced pods, and identify bad deploys. Use this skill whenever an incident, ServiceNow ticket, or user mentions gateway errors, 5xx/4xx, Kibana, Elastic logs, istio-proxy, Envoy response flags, x-request-id, pod restarts, secret not found, or asks "why is app X failing" — even if Kibana is not named explicitly.
---

# Kibana K8s / Istio Incident Triage

Diagnose application and gateway failures **from Kibana logs alone**. Cluster access is not required; Kubernetes commands appear only as optional read-only cross-checks.

## Hard rules

- **Read-only.** Never suggest or run `kubectl delete`, `exec`, `edit`, `scale`, `rollout restart`, or any mutating action. Diagnosis only.
- **Filter by labels, never by a single pod name.** Pods get replaced; logs of dead pods remain in Elastic and must be included.
- **Always pin an absolute time window** from the incident timestamp. Convert the ticket's timezone to the Kibana/UTC timezone explicitly and state the conversion.
- **Verify field names before building queries** (Step 0). Never assume ECS names are correct.
- **Report evidence, not guesses.** Every conclusion must cite the query used and a sample log line (request id, timestamp, pod).

## Inputs

| Input | Required | Notes |
|---|---|---|
| `NS` | yes | App namespace |
| `APP` | yes | Value of the `app` label (fallback: deployment name prefix) |
| `INCIDENT_TIME` | yes | From ticket; convert to UTC |
| `SVC` | derive | K8s Service name; often = APP but not always |
| `ERROR` | optional | e.g. 502, 404, "secret missing", "gateway error" |
| `REQUEST_ID` | optional | `x-request-id` if the ticket has one |
| `GW_NS` / `GW_APP` | default | `istio-system` / `istio-ingressgateway` unless told otherwise |

Default window: `INCIDENT_TIME - 15m` to `INCIDENT_TIME + 15m`. Widen to ±2h if nothing is found, or if the ticket was raised well after the impact started.

## Step 0 — Discover field names

Fetch one recent doc for the app and map the actual names onto the placeholders used below. See `references/field-mapping.md` for the common variants (Filebeat/ECS, Fluent Bit, Fluentd, Istio text vs JSON access logs).

| Placeholder | Common ECS name |
|---|---|
| `{ns}` | `kubernetes.namespace` |
| `{app}` | `kubernetes.labels.app` |
| `{pod}` | `kubernetes.pod.name` |
| `{container}` | `kubernetes.container.name` |
| `{image}` | `container.image.name` |
| `{level}` | `log.level` |
| `{msg}` | `message` |
| Envoy fields | `response_code`, `response_flags`, `upstream_cluster`, `upstream_host`, `authority`, `path`, `method`, `x_request_id`, `duration` |

If the Envoy fields don't exist as structured fields, the access logs are unparsed text. Use `{msg}` wildcards (see `references/field-mapping.md`) and flag "ingest pipeline needed" in the report.

## Base filter (reused everywhere)

```
BASE      = {ns} : "NS" and {app} : "APP"
APP_LOGS  = BASE and not {container} : "istio-proxy"
SIDECAR   = BASE and {container} : "istio-proxy"
GATEWAY   = {ns} : "GW_NS" and {app} : "GW_APP"
SVC_MATCH = upstream_cluster : *SVC.NS.svc.cluster.local*
```

## Workflow — pick by symptom, then always finish with Step 6

### Step 1 — Gateway error (ticket says "gateway error", 502/503/504 at the edge)

```
GATEWAY and SVC_MATCH and (response_code >= 500 or response_code : 0)
```

If the app is unknown, drop `SVC_MATCH`, run `GATEWAY and response_code >= 500`, and aggregate by `upstream_cluster` to find the failing service.

Collect:
- count by `response_code` × `response_flags`
- top `path`
- first and last timestamps of errors (is it ongoing?)
- 3 sample `x_request_id`s

Then go to Step 2 with one sample id.

### Step 2 — Trace one request end to end

```
x_request_id : "REQUEST_ID"
```

No time filter is needed beyond ±1h. Order the hits by `@timestamp`. The **last hop that logged** is where it broke:

| Seen in | Not seen in | Conclusion |
|---|---|---|
| gateway | app sidecar | Never reached pod: routing, no endpoints, mTLS. Use the gateway `response_flags`. |
| app sidecar (inbound) | app container | Sidecar → app failed: app down, wrong port, crashed. |
| app container | — | App handled it. Check its error log and outbound calls (Step 4). |
| app sidecar outbound with 5xx | — | Dependency failure; name it from `upstream_cluster`/`authority`. |

### Step 3 — 5xx / 404 at the app

```
SIDECAR and upstream_cluster : inbound* and response_code : (502 or 503 or 504 or 404)
```

| Code + flag | Meaning |
|---|---|
| 502 + `UF`/`UC`/`URX` | Sidecar couldn't reach the app container |
| 502 + `-` | App itself returned 502, usually a dependency failure (Step 4) |
| 503 + `UH` | No healthy endpoint / pods not ready |
| 503 + `UO` | Circuit breaker / connectionPool overflow |
| 504 + `UT` | App too slow or VS timeout too low |
| 404 + `NR` | Mesh routing: VirtualService host/path mismatch |
| 404 + `-` | App has no such path: check `path` for typo or version skew |

Full flag table: `references/envoy-response-flags.md`.

If there are **no inbound sidecar logs** for the window but the gateway shows errors, the request never reached the pod. Go back to the Step 1 flags.

### Step 4 — Outbound calls / dependencies

```
SIDECAR and upstream_cluster : outbound*
```

Aggregate `authority` → `path` → `method`, with count and `response_code` breakdown. A dependency with a 5xx spike in the same window is a likely root cause. Note any cross-namespace dependency (`*.other-ns.svc.cluster.local`) and recurse this skill on that service if it is failing.

Caveats:
- The app does TLS itself (HTTPS to external hosts): only host/SNI is visible, no path.
- High-cardinality paths (`/users/123`): group by `authority` first.

### Step 5 — App errors, missing secrets/config

App logs in the window:
```
APP_LOGS and ({level} : (ERROR or FATAL or WARN) or {msg} : (*Exception* or *error* or *failed* or *refused* or *timeout*))
```

Secret / config / identity failures:
```
APP_LOGS and {msg} : (*secret* or *keyvault* or *KeyVault* or *credential* or *"not found"* or *Unauthorized* or *Forbidden* or *"Could not resolve placeholder"* or *"environment variable"* or *BeanCreationException* or *"APPLICATION FAILED TO START"*)
```

(Spring Boot apps: `Could not resolve placeholder`, `BeanCreationException`, and `APPLICATION FAILED TO START` are the usual signatures of missing config or secrets.)

Pod never started (no app logs exist), so use Kubernetes events, **only if they are shipped to Elastic**:
```
kubernetes.event.involved_object.namespace : "NS"
and kubernetes.event.involved_object.name : APP*
and kubernetes.event.type : "Warning"
```
Look for reasons `CreateContainerConfigError`, `FailedMount` (secret/configmap/CSI Key Vault), `BackOff`, `OOMKilling`, `Unhealthy`. If no events index exists, report "K8s events not shipped; cannot confirm from Kibana" and give the read-only cross-check `kubectl get events -n NS`.

### Step 6 — Pod lifecycle and deploy correlation (always run)

```
BASE
```

Aggregate per `{pod}`: `{image}` (tag), min `@timestamp`, max `@timestamp`.

- A pod whose max timestamp falls inside the window **died during the incident**. Read its last ~50 app log lines (`APP_LOGS and {pod} : "<pod>"`, sorted descending).
- A new image tag that starts just before errors begin indicates a **likely bad deploy**. Report the old tag → new tag and the start time.
- A pod that stops logging abruptly with no error lines suggests OOMKill or a node issue. Confirm via events if available.

### Step 7 — Sanity checks when results are empty

1. Other apps have logs in the same window? If not, the log shipper was down or the window is outside retention.
2. Is the window right? Re-check the timezone conversion.
3. Is the app label wrong? Retry with `{pod} : APP-*`.
4. Is access logging disabled in the mesh? (No istio-proxy docs at all.) Report it; the read-only check is `kubectl get telemetry -A` / meshConfig `accessLogFile`.

## Optional NGINX Plus / F5 in front

If the gateway shows **no** matching errors but users see 502/504, the request likely failed before the mesh. Query the edge LB logs for the same window and host, and state "failure upstream of Istio gateway".

## Output format

Return to the user / orchestrator:

```
Incident: <ticket id>  | Window (UTC): <from> – <to>  | NS/APP: <ns>/<app>
Field mapping used: <placeholders → actual fields>

Symptom:     <code(s), count, paths, first/last seen>
Failing hop: <gateway | sidecar→app | app | dependency X | pod never started>
Evidence:    <query> → <1-3 sample lines with request id, pod, timestamp>
Pods/deploy: <pods alive in window, restarts, image tag change at T>
Likely cause: <one sentence>  Confidence: <high|medium|low>
Gaps:        <missing events index, unparsed access logs, retention, etc.>
Next checks (read-only): <kubectl get/describe, istioctl proxy-config ...>
```

## References

- `references/field-mapping.md`: field name variants and text-log fallbacks. Read during Step 0.
- `references/envoy-response-flags.md`: full Envoy flag table with causes.
- `references/es-dsl.md`: Elasticsearch query DSL and aggregation equivalents, for agents calling the ES/Kibana API instead of using KQL in Discover.
