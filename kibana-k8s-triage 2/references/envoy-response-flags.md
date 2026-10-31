# Envoy verdict decoder (Istio access logs)

Read four fields together: `response_code` + `response_flags` + `response_code_details` + `upstream_transport_failure_reason`. Details is the most precise; always aggregate on it.

## Response flags

| Flag | Meaning | Typical cause |
|---|---|---|
| - | No flag | Upstream produced the code; app or its dependency is responsible |
| NR | No route | VirtualService host/path/port mismatch, Gateway not bound, wrong `hosts`; TCP: `filter_chain_not_found` |
| UH | No healthy upstream | 0 ready endpoints (probe failing, scaled 0, selector mismatch) or all outlier-ejected |
| UF | Upstream connection failure | Wrong targetPort, app not listening, mTLS mismatch, TLS error, app still starting |
| UC | Upstream connection termination | App closed conn; keepalive mismatch; crash mid-request |
| URX | Retry/connect limit exceeded | Repeated connect failures or 5xx; app flapping |
| UT | Upstream request timeout | Slow app/dependency; VS `timeout` too low |
| UO | Upstream overflow | DestinationRule connectionPool / circuit breaker |
| UR | Upstream remote reset | App/dependency reset the stream (RST) |
| LR | Local reset | Envoy reset (timeout, proxy limit) |
| LH | Local health check failed | Active HC failure (rare in Istio) |
| DC | Downstream connection termination | Client gave up; client/LB timeout < request time |
| DI / FI | Fault injection delay / abort | VS `fault` configured — check for leftovers from testing |
| RL | Local rate limited | Local rate limit filter (429) |
| RLSE | Rate limit service error | External RLS unreachable |
| UAEX | Unauthorized by ext_authz | AuthorizationPolicy CUSTOM / ext_authz denied |
| NC | Upstream cluster not found | Missing Service/ServiceEntry, stale config |
| DT | Duration timeout | `max_stream_duration` / `max_connection_duration` |
| DPE | Downstream protocol error | Bad client request, HTTP/2 framing, header too large |
| UPE | Upstream protocol error | Port name/protocol wrong (`http` vs gRPC/TLS), app sends non-HTTP |
| UMSDR | Upstream max stream duration | Long-lived stream cut |
| OM | Overload manager | Proxy memory pressure — sidecar resource limits |
| SI | Stream idle timeout | `idle_timeout` hit (long polls, SSE, slow downloads) |
| DF | DNS resolution failure | DNS-type ServiceEntry / STRICT_DNS cluster can't resolve |
| DO | Drop overload | Admission control / overload drop |

`response_code: 0` = no HTTP response (connection-level), usually with DC/UC/UF, or any TCP proxy line (Kafka, Cassandra, DB) — normal for TCP.

## response_code_details (high value)

| Value | Meaning |
|---|---|
| `via_upstream` | App returned it — go to app logs |
| `route_not_found` | No VS route matched (host/path/method/header) |
| `cluster_not_found` | Route points to a non-existent cluster |
| `no_healthy_upstream` | No endpoints / all ejected |
| `upstream_reset_before_response_started{connection_failure}` | Could not connect |
| `...{connection_failure,TLS_error:...}` | TLS/mTLS handshake failed → `playbooks/tls-certs.md` |
| `...{connection_termination}` | Upstream closed (keepalive / crash) |
| `...{remote_reset}` / `{remote_refused_stream_reset}` | Upstream RST / HTTP2 refused |
| `...{overflow}` | Circuit breaker |
| `...{local_reset}` | Envoy reset |
| `upstream_reset_after_response_started{...}` | Partial response; app died mid-stream |
| `upstream_response_timeout` | Route timeout |
| `upstream_per_try_timeout` | Retry per-try timeout |
| `request_overall_timeout` / `stream_idle_timeout` / `duration_timeout` | Downstream-side timeouts |
| `downstream_remote_disconnect` | Client hung up |
| `rbac_access_denied_matched_policy[ns.policy]` | AuthorizationPolicy DENY / no ALLOW match (403) |
| `ext_authz_denied` / `ext_authz_error` | External auth said no / external auth broken |
| `jwt_authn_access_denied{Jwt is expired}` | Token expired |
| `jwt_authn_access_denied{Jwks remote fetch is failed}` | Can't reach JWKS (egress/DNS/cert to IdP) |
| `jwt_authn_access_denied{Jwt issuer is not configured}` | Issuer mismatch (wrong tenant/env) |
| `local_rate_limited` | 429 from local RL |
| `request_payload_too_large` / `response_payload_too_large` | Buffer limit (413 / 500) |
| `request_headers_failed_strict_check` / `header_overflow` | Header validation / size (400/431) |
| `codec_error` / `http1.codec_error` / `http2.*` | Protocol violation |
| `lua_response` / `wasm_fail_stream` / `direct_response` | EnvoyFilter (Lua/Wasm) or VS direct response produced it |
| `filter_chain_not_found` | Listener had no matching chain (SNI/port/protocol) |
| `overload_manager` | Proxy overload |
| `cluster_header_not_found` / `maintenance_mode` | Misconfig / cluster in maintenance |

## upstream_transport_failure_reason

| Contains | Meaning |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` | Upstream cert not trusted (CA mismatch, wrong root, self-signed) |
| `SSLV3_ALERT_CERTIFICATE_EXPIRED` / `CERTIFICATE_EXPIRED` | Expired cert (peer alert = the other side's view of *our* cert) |
| `SSLV3_ALERT_CERTIFICATE_UNKNOWN` / `TLSV1_ALERT_UNKNOWN_CA` | Peer rejected our client cert / CA |
| `WRONG_VERSION_NUMBER` | Speaking TLS to plaintext port (or vice versa) — DestinationRule TLS mode vs app |
| `SSLV3_ALERT_HANDSHAKE_FAILURE` / `NO_SHARED_CIPHER` | Cipher/protocol mismatch |
| `TLSV1_ALERT_PROTOCOL_VERSION` | TLS version mismatch (TLS1.0/1.1 on legacy targets) |
| `verify cert failed: SAN` / `verify_subject_alt_name` | SAN mismatch (`subjectAltNames` in DR, wrong hostname) |
| `delayed connect error: 111` | Connection refused (port closed) |
| `delayed connect error: 113` / `110` | No route to host / timed out (network, NetworkPolicy, firewall) |

## connection_termination_details

Present when Envoy closed the connection itself; e.g. `rbac_access_denied_matched_policy[none]` on TCP (Kafka/Cassandra blocked by AuthorizationPolicy).

## Common combos

| Combo | Read as |
|---|---|
| 503 UF `connection_failure` + `delayed connect error: 111` | App not listening on targetPort (crash, wrong port, still starting) |
| 503 UF + `TLS_error` at gateway → app | mTLS: PeerAuthentication STRICT vs DR DISABLE, or sidecar missing on target |
| 503 UH right after rollout | New pods not ready, old already gone (maxUnavailable / probe) |
| 503 UC `connection_termination` sporadic | App idle timeout < Envoy idle timeout (Tomcat `keepAliveTimeout`, Netty) |
| 502 `-` `via_upstream` | App returned 502 — its dependency failed |
| 504 UT with `upstream_service_time` ≈ VS timeout | Route timeout hit; find slow dependency |
| 0 DC with long `duration` | Client/LB/Apigee timed out first; server still working |
| 404 NR after release | VS changed or canary subset missing |
| 503 NC | DR/VS references subset with no matching pods (`version` label) |
| 403 RBAC across many apps at once | New/changed AuthorizationPolicy |
| 401 `jwt_authn` spike all apps | IdP key rotation / JWKS unreachable |
