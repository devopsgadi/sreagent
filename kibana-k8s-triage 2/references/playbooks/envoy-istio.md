# Playbook — Envoy / Istio

Entry: gateway or sidecar access logs show a non-`via_upstream` failure, or `ENV-*` signatures.

## 1. Locate the deciding proxy
- Gateway proxy decided (flags at gateway, nothing at app sidecar) → routing, endpoints, mTLS, gateway TLS, auth filters on gateway.
- App inbound sidecar decided → local app / inbound auth / port.
- App outbound sidecar decided → dependency, egress, DR to target.

## 2. Decision tree by details

**route_not_found / NR (404)**
- Aggregate `authority` + `path` + `method`. Host typo? Path prefix changed in release? Canary header/cookie match missing?
- Same path works in baseline → VS changed at release (check new RS of nothing — VS isn't a pod; correlate with Argo CD/istiod push time).
- Only one host failing behind gateway → Gateway `hosts` / VS `gateways` binding.

**no_healthy_upstream / UH (503)**
- Inbound traffic to target pods in same window? None → no Ready endpoints. Go to `k8s-from-logs.md` (rollout gap, probe failing, crash loop).
- Some pods receiving, errors intermittent → outlier detection ejecting pods. Look for per-pod 5xx spikes before UH; consecutive 5xx triggers ejection.
- UH only for one subset → subset label selector matches no pods (`version` label typo) or canary scaled to 0.

**connection_failure / UF (503)**
- `delayed connect error: 111` → nothing listening. App crashed/starting, wrong `targetPort`, app bound to 127.0.0.1 only.
- `TLS_error` → `tls-certs.md` §mTLS.
- Only right after pod start → app accepts before ready; check `holdApplicationUntilProxyStarts` gap (app calls out before sidecar ready → outbound fails at startup: `Connection refused` to 15001).

**connection_termination / UC (503)**
- Sporadic, low rate, all pods → keepalive race: app idle timeout shorter than Envoy's (Tomcat `keepAliveTimeout` default 20s/connectionTimeout; Netty). Fix: app idle > Envoy idle (`idleTimeout` in DR) or Envoy retries on `reset`.
- Burst on one pod then stops → pod died mid-request (correlate lifecycle).

**upstream_response_timeout / UT (504)**
- `duration` ≈ VS timeout value → route timeout; also check Apigee / gateway / client timeouts — the smallest wins.
- Find slow hop: target's outbound `p95` per dependency in same window.
- `upstream_per_try_timeout` + retries → retries multiplying load (retry storm). Count attempts per request id.

**overflow / UO (503)**
- DR `connectionPool.http.http1MaxPendingRequests`/`maxRequestsPerConnection`/`tcp.maxConnections` too low for traffic or target slow (queue builds). Correlate with latency rise on target.

**DC / response_code 0**
- Client side timeout. Compare `duration` to known client timeouts (Akamai 120s origin default, Apigee target timeout, F5/NGINX `proxy_read_timeout`, browser). Server-side cause is still slowness.

**403 rbac_access_denied_matched_policy[...]**
- Policy name inside brackets (`ns-x.deny-all`). `[none]` = no ALLOW matched (default deny when any ALLOW policy exists for workload).
- Caller identity: source principal is not in text logs by default; infer from `downstream_remote_address` → pod IP → pod (match `{pod_ip}`).
- Sudden mesh-wide 403 → new policy rollout.

**401/403 jwt_authn / ext_authz**
- `Jwt is expired` from one client → client issue. Mesh-wide `Jwks remote fetch is failed` → IdP/egress/DNS/cert to IdP.
- `ext_authz_error` → auth service down (recurse on it); `ext_authz_denied` → policy decision.

**BlackHoleCluster / NC**
- Egress to host not registered. New external dependency in release without ServiceEntry, or ServiceEntry removed.

**DPE / UPE / codec_error**
- UPE: Service port named `http` but app speaks TLS/gRPC/HTTP2, or port name `grpc` for HTTP/1.1. DPE: malformed client (large headers → 431, bad HTTP2).

**RL / local_rate_limited / 429**
- Rate limit filter (EnvoyFilter / Telemetry); confirm whether 429s come from Envoy (flag RL) or app (`via_upstream`).

**lua_response / wasm_fail_stream / direct_response**
- An EnvoyFilter or VS directResponse produced it. Wasm plugin crash → `wasm` lines in sidecar logs.

## 3. Sidecar and control plane health
- `ENV-01/02` → istiod unreachable/slow: check istiod logs same window (`{ns}:istio-system and {app}:istiod`), especially `ERROR`, `push`, `context deadline exceeded`, OOM restarts.
- `ENV-03` NACK → a config (EnvoyFilter, DR, VS) rejected by proxies; the rejected resource name is usually in the message.
- `ENV-05` → sidecar crash; check `OM` flags and memory-related lines.
- Mesh-wide burst of 503s exactly at an istiod push time → config regression.

## 4. Retries and amplification
For one failing `x_request_id`, count gateway vs sidecar lines. >1 inbound lines per request id = retries. Default Istio retries 2 on `connect-failure,refused-stream,unavailable,cancelled,retriable-status-codes(503)`. Retry storms multiply load on a struggling dependency — call it out.

## 5. Escalation asks (cluster-only)
`istioctl proxy-config routes|clusters|endpoints <pod>`, `istioctl analyze -n NS`, `kubectl get vs,dr,pa,authorizationpolicy -n NS -o yaml`, endpoint membership.
