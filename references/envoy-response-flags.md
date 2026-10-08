# Envoy response flags (Istio access logs)

| Flag | Meaning | Typical cause / where to look |
|---|---|---|
| - | No flag | Response came from upstream as-is; the app (or its dependency) produced the code |
| NR | No route configured | VirtualService host/path/port mismatch, Gateway not bound, wrong `hosts` |
| UH | No healthy upstream | 0 ready endpoints: pods not ready, failing readiness probe, scaled to 0, selector mismatch |
| UF | Upstream connection failure | Wrong targetPort, app not listening, mTLS mode mismatch (PeerAuthentication vs DestinationRule) |
| UC | Upstream connection termination | App closed the connection; keepalive/idle timeout mismatch; app crash mid-request |
| URX | Upstream retry limit exceeded | Repeated connect failures/5xx; app flapping |
| UT | Upstream request timeout | Slow app/dependency; VirtualService `timeout` too low |
| UO | Upstream overflow | DestinationRule connectionPool / circuit breaker limits hit |
| UR | Upstream remote reset | App/dependency reset the stream |
| LR | Local reset | Envoy reset (often a timeout or resource limit on the proxy) |
| DC | Downstream connection termination | Client gave up: client timeout, LB idle timeout shorter than the request |
| DI | Delayed via fault injection | Fault injection configured in VS |
| FI | Aborted via fault injection | Fault injection configured in VS |
| RL | Rate limited locally | Local rate limit filter |
| RLSE | Rate limit service error | External rate limit service unreachable |
| UAEX | Unauthorized by external auth | ext_authz / AuthorizationPolicy CUSTOM denied |
| NC | Upstream cluster not found | Missing ServiceEntry/Service, stale config |
| DT | Duration timeout | max_stream_duration exceeded |
| DPE | Downstream protocol error | Bad client request (HTTP/2 or headers) |
| UPE | Upstream protocol error | App speaking wrong protocol on port (e.g. port name `http` vs actual gRPC/TLS) |
| UMSDR | Upstream max stream duration reached | Long-lived stream cut |
| OM | Overload manager | Proxy under memory pressure |

`response_code : 0` means no response was sent (connection-level failure), usually paired with DC/UC/UF.

403 with `RBAC` in response_code_details means an AuthorizationPolicy denied it, not the app.
