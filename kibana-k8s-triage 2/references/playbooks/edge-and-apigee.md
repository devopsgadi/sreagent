# Playbook — Edge (Akamai, F5, NGINX Plus) and Apigee

Entry: users see errors but Istio gateway shows none (or fewer) for the host/window; or gateway shows `response_code 0` + `DC`; or API path goes through Apigee.

## 1. Find the last hop that saw the request
Order of hops: Akamai → (F5 / NGINX Plus) → Istio ingress gateway → service. For APIs: client → Akamai → Apigee → (F5/NGINX) → gateway → service, and services → Apigee → mainframe/Hogan/partners (routing key selects the target).

Correlation keys:
| Hop | Key |
|---|---|
| Akamai | `Reference #18.xxxx` (error page), `X-Akamai-Request-ID`, `AKA_*` headers; DataStream logs if indexed |
| Apigee | `messageid`, `apigee-request-id`, `x-request-id` if propagated |
| NGINX Plus | `$request_id` if logged as `X-Request-ID` |
| Istio | `x-request-id` (generated if absent — so edge id often differs; correlate by time + path + client IP via `x_forwarded_for`) |

## 2. NGINX Plus / F5 log signals
| Signal | Meaning |
|---|---|
| `upstream timed out (110: Connection timed out) while reading response header` | Gateway/backend slower than `proxy_read_timeout` |
| `connect() failed (111: Connection refused)` / `no live upstreams` | Gateway nodes/NodePorts/LB VIP unreachable; health checks failed |
| `upstream prematurely closed connection` | Gateway closed (Envoy idle timeout < NGINX keepalive) |
| `SSL_do_handshake() failed` / `upstream SSL certificate verify error` | TLS to gateway (cert rotation on gateway) |
| 499 | Client closed (Akamai/browser timeout) |
| 502/504 with `upstream_response_time` near limit | Timeout chain |
| F5: pool member down, `monitor` status changes, `RST` reasons | LB health/routing |

If the edge says it sent the request and the gateway has no matching line (time ±2s, path, client IP) → LB → gateway network path (NodePort, VIP, firewall, Panorama policy).

## 3. Apigee
| Evidence | Meaning |
|---|---|
| `fault.name` = `GatewayTimeout` / `messaging.adaptors.http.flow.GatewayTimeout` (504) | Target exceeded Apigee target timeout |
| `ServiceUnavailable` / `NoActiveTargets` (503) | Target server down / TLS to target failed |
| `ApplicationNotFound`, `InvalidApiKey`, `invalid_access_token`, `access_token_expired` (401) | Consumer credential issue — not backend |
| `SpikeArrestViolation` / `QuotaViolation` (429) | Policy limit |
| `ErrorResponseCode` from target, `target.response.status.code` | Backend returned error — go into mesh |
| Routing key → wrong target env | Requests reaching wrong backend (e.g. UAT key → IT backend) — compare `authority`/target URL with routing key |

Apigee target timeout vs Istio VS timeout vs app timeouts: the smallest fires first. State the chain.

## 4. Akamai
- Akamai errors (`Reference #`) with no origin log → origin unreachable from Akamai (allowlist, origin cert, F5 VIP).
- Origin timeout default 120s (property-dependent) → DC at gateway with ~120s duration.
- Stale cached content (micro-apps) → see `microapps-frontend.md`.

## 5. Output
State the last hop that logged the request, the edge error text, and whether failure is "upstream of Istio gateway". Escalation asks: Akamai log/purge, F5 pool status, Panorama policy hit logs, Apigee trace session.
