# Playbook — Spring Boot services

Entry: app container is the failing hop, or `CFG/SEC/HTTP/DB/RD/MQ/MF/JVM/LIF` signatures.

## 1. Did it start?
| Evidence | Meaning |
|---|---|
| `Started XApplication in N seconds` | Started. Compare N with baseline starts and probe delays |
| CFG-01 `APPLICATION FAILED TO START` | Read the `Description:` and `Action:` block that follows — Boot states the cause plainly |
| CFG-02 `Could not resolve placeholder 'x'` | Property missing: ConfigMap key, env var, Key Vault secret name, profile not active (`spring.profiles.active`) |
| CFG-03 `BeanCreationException` | Read the deepest `Caused by:` — usually DB/Kafka/Key Vault connection at startup or missing property |
| CFG-05 Cloud Config | Config server down / wrong label/branch / auth |
| SEC-01..05 | Key Vault secret missing, identity token failure, client secret expired, RBAC — see table below |
| No logs at all from new RS | Container never ran → `k8s-from-logs.md` §never started |
| `The following profiles are active:` | Confirm the env profile (UAT pod with PROD profile, etc.) |

### Azure identity / Key Vault
| Code / text | Meaning |
|---|---|
| `AADSTS7000222` | Client secret expired |
| `AADSTS7000215` | Wrong client secret |
| `AADSTS700016` | App (client id) not found in tenant — wrong tenant/env |
| `AADSTS70021` / `AADSTS700213` | Federated credential (workload identity) subject/issuer mismatch — SA name/namespace changed |
| `ManagedIdentityCredential authentication unavailable` | IMDS/pod identity not reachable (aad-pod-identity/NMI or workload identity webhook missing) |
| `SecretNotFound` / `(SecretNotFound) A secret with (name/id) x was not found` | Secret name wrong or not created in this env's vault |
| `ForbiddenByPolicy` / `ForbiddenByRbac` | Identity lacks get/list on secrets |
| `Status code 429` from vault | Key Vault throttling (many pods starting at once) |

## 2. It started — what is it failing on?
Rank surviving signatures by first-seen. Typical chains:

| Chain | Root |
|---|---|
| DB-01 Hikari timeout → HTTP 500/503 → gateway 503/504 | DB slow/unreachable or pool too small for load or connection leak |
| HTTP-02 read timeout to service B → HTTP-07 breaker open → fast 503s | Service B slow (recurse on B) |
| HTTP-04 UnknownHost → all calls to X fail | DNS / ServiceEntry / host renamed |
| HTTP-05 Connection reset / PrematureClose sporadic | Keepalive mismatch with Envoy/peer (idle timeout). Not a capacity issue |
| HTTP-10 pool exhausted → latency | Outbound HTTP client pool too small vs slow dependency |
| HTTP-11 401 from Apigee/downstream | Token/credential expired or client-id change; Apigee routing key wrong env |
| JVM-01 OOM → restart → UH bursts | Memory: heap vs container limit; leaks; large payloads |
| DB-02 clock leap / long GC → everything slow on one pod | CPU throttling / GC; node-local |
| MQ-01 / MF-01 → mainframe/Hogan path errors | Mainframe channel / QM / CICS region; check other apps using same route |

### Hikari specifics
- `Connection is not available, request timed out after 30000ms (total=10, active=10, idle=0, waiting=N)` → pool saturated. `active=total` & DB fine → slow queries or leak (`Apparent connection leak detected` with leakDetectionThreshold).
- `Failed to validate connection` / `Connection marked as broken` → DB/network dropped connections (firewall idle kill, DB failover). Azure SQL failover / Oracle RAC switchover shows as burst then recovery.
- `HikariPool-1 - Exception during pool initialization` → DB unreachable at startup.

### Resilience4j
- `CircuitBreaker 'x' is OPEN and does not permit further calls` → **effect**, not cause. Find what failed before it opened (the first errors for 'x').
- `BulkheadFullException` → concurrency limit; downstream slow.
- Retry logs multiply downstream load; note count.

### Web servers
- Tomcat: `max threads` reached isn't logged by default; infer from rising latency + inbound UT; `RejectedExecutionException` on async pools.
- Netty/WebFlux: `Pending acquire queue has reached its maximum size` (reactor-netty pool), `blocking call` detected (BlockHound).
- `ClientAbortException` / `Broken pipe` → client (Envoy) closed first: client timeout (correlate DC/UT at sidecar).

## 3. Version / config change inside app
- `Starting X v<ver>` line or `/actuator/info` build version in logs — compare old vs new pods.
- `Refresh keys changed: [...]` (Cloud Bus / config refresh) → runtime config change without rollout.
- Feature flag logs (LaunchDarkly/Unleash) changes at error start.

## 4. Logging gaps to flag
- No `traceId` in logs → can't follow cross-service; recommend Micrometer Tracing + logstash encoder.
- Stack traces split into separate docs (multiline not configured) → search exception class only.
- Log level WARN only → INFO lifecycle markers missing.

## 5. Output
Name the first failing call (dependency + exception + count + first seen), the effect chain, and whether it's pod-local, app-wide, or shared-dependency-wide.
