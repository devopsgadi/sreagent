# Kubernetes state from logs alone

No kubectl. Everything below is inferred from log documents. State the inference and its strength; put cluster-only confirmations in `Escalation asks`.

## Pod name anatomy

`orders-api-7d9f8c6b5-x2k4p` → deployment `orders-api`, ReplicaSet hash `7d9f8c6b5`, pod suffix `x2k4p`.
StatefulSet: `cassandra-0` (ordinal, no RS hash). Job/CronJob: `name-<epoch>-<suffix>`.

| Observation | Inference | Strength |
|---|---|---|
| New RS hash appears | Rollout (pod template changed: image, env, ConfigMap ref, annotation, resources) | Strong |
| New RS hash, same image tag | Config/secret/resource change or forced restart annotation (Argo CD sync, `kubectl rollout restart`) | Strong |
| Old RS pods stop, new RS pods start, overlapping | Normal rolling update | Strong |
| Old RS pods stop before new RS pods log `Started` | Capacity gap → 503 UH during rollout | Medium |
| New pod names, same RS hash | Pod replaced (crash/eviction/node loss/scale) | Strong |
| Pod count per RS rises over minutes | HPA scale-up (load) | Medium |
| Pod count drops, pods log graceful shutdown | Scale-down / HPA | Medium |
| Two RS hashes active long term, different `version` label | Canary (stable/next) | Strong |

## Restart vs replacement

| Pattern in a single pod name | Meaning |
|---|---|
| Spring Boot banner / `Starting XApplication` seen 2+ times | Container restarted in place (crash or liveness kill) |
| Last line is normal, then gap, then `Starting` | SIGKILL: OOMKilled or liveness failure |
| `Commencing graceful shutdown` then `Starting` | Liveness kill with SIGTERM honoured, or manual restart |
| `OutOfMemoryError` then gap then `Starting` | JVM OOM → crash (`-XX:+ExitOnOutOfMemoryError`) |
| No OOM text, abrupt stop, restart | Kernel OOMKill (container memory limit) — heap fits, total RSS doesn't (metaspace, threads, direct buffers) |
| `Starting` repeating every 1–5 min with growing gaps | CrashLoopBackOff (backoff 10s→5m) |
| istio-proxy logs continue while app container silent | App container dead/restarting; sidecar alive → inbound 503 UF `connection refused` |
| Both containers stop at same instant | Pod deleted/evicted or node gone |

## Probes (Istio rewrites them)

With sidecar injection, kubelet probes hit pilot-agent on `:15020/app-health/<container>/readyz|livez|startupz`, which forwards to the app.

| Signal | Meaning |
|---|---|
| Sidecar/pilot-agent lines with `/app-health/` failing | App health endpoint failing or slow |
| App logs `Readiness state changed to REFUSING_TRAFFIC` | Boot marked itself not ready (dependency health indicator down, e.g. DB/Kafka/Redis in health group) |
| `Started X in 140 seconds` with probe initialDelay < that | Liveness killing app during slow start → restart loop |
| `/actuator/health` 503 in inbound access logs | Health group includes a failing dependency |
| `Envoy proxy is NOT ready` repeating | Sidecar not ready (istiod/xDS, cert) → pod not Ready → UH |

## Node-level signals

- Group last-log times by `{node}`. Several unrelated pods on one node going silent within the same minute = node failure, kubelet restart, network partition, or node drain (graceful shutdown lines present → drain/upgrade).
- AKS upgrades / on-prem patching produce waves of graceful shutdowns across nodes in sequence.
- Errors only from pods on one node (`DB-02` clock leap, timeouts) = noisy neighbour, CPU throttling, disk pressure.

## Scheduling / never started

If a new RS hash has **no app logs at all**, the pod never ran its container. Causes: ImagePullBackOff, CreateContainerConfigError (missing secret/ConfigMap key), FailedMount (CSI Key Vault), Pending (resources/quota/affinity), init container failing. Kibana-only:

1. Events index present → `es-dsl.md` §K8s events.
2. Init container logs: `{container}` values other than app / istio-proxy (`istio-init`, `istio-validation`, custom inits).
3. CSI Key Vault provider logs (`kube-system`, `*secrets-store*`, `*csi-azure*`).
4. Otherwise: report "pod created no logs; cause needs `kubectl describe pod` — escalation ask".

## Deploy / change correlation without GitLab access

| Evidence | Where |
|---|---|
| Image tag change | `{image}` per RS hash |
| Boot version info | App logs `Starting X v1.2.3 using Java 17`, `build.version` in info logs |
| Config change | New RS hash without image change; Spring `Refresh keys changed` (Cloud Config bus) |
| Argo CD sync | `{ns}:argocd` logs with app name, `Sync operation`, `Updated health status` |
| Mesh config change | istiod `Push debounce`, `Full push`; sidecars `ads` updates at same minute |
| Cert rotation | cert-manager `Certificate issued`, istiod CA rotation |
| Audit log (if indexed) | `objectRef.resource:(deployments or configmaps or virtualservices or destinationrules or authorizationpolicies)` and `verb:(patch or update or create or delete)` |

Change at T, errors begin T+0..5m → likely cause. Errors before change → change is not the cause (state it).

## What logs cannot tell you (always list as gaps when relevant)

- Current Ready/NotReady status, restart counts, exit codes (unless events shipped)
- Resource limits/requests and actual memory/CPU (use Datadog/metrics if available)
- Endpoint membership of a Service (infer from inbound traffic per pod)
- Exact VirtualService/DestinationRule/AuthorizationPolicy content (infer from flags and details)
