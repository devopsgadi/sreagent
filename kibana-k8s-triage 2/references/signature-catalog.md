# Signature catalog

Master list of log signatures. The agent runs these as one `filters` aggregation (one bucket per ID) over the incident window and the baseline window, then reports IDs that are **new** or grew **≥3×**. KQL shown against `{msg}`; add `{stack}`/`{exc}` where stack traces are separate fields. Each ID maps to a playbook.

Scope: `APP` = app container logs, `SC` = istio-proxy logs (non-access), `GW` = gateway, `ANY` = any.

## Startup / config / secrets — `playbooks/springboot.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| CFG-01 | APP | `*"APPLICATION FAILED TO START"*` | Boot startup failure; read next 30 lines |
| CFG-02 | APP | `*"Could not resolve placeholder"*` | Missing property / env / ConfigMap key |
| CFG-03 | APP | `*BeanCreationException*` or `*UnsatisfiedDependencyException*` | Wiring failure (often config/secret) |
| CFG-04 | APP | `*"Failed to bind properties"*` or `*BindException*` | Bad property value/type |
| CFG-05 | APP | `*"Could not locate PropertySource"*` or `*ConfigClientFailFast*` | Spring Cloud Config server unreachable |
| CFG-06 | APP | `*"Port 8080 was already in use"*` or `*"Address already in use"*` | Port clash |
| CFG-07 | APP | `*ClassNotFoundException*` or `*NoSuchMethodError*` or `*NoClassDefFoundError*` | Bad build / dependency skew |
| SEC-01 | APP | `*SecretNotFound*` or `*"Secret not found"*` or `*"A secret with (name"*` | Key Vault secret missing / wrong name |
| SEC-02 | APP | `*ManagedIdentityCredential*` or `*WorkloadIdentityCredential*` or `*"DefaultAzureCredential failed"*` | Azure identity token failed |
| SEC-03 | APP | `*AADSTS7000222*` or `*AADSTS7000215*` | Client secret expired / invalid |
| SEC-04 | APP | `*AADSTS700016*` or `*AADSTS70021*` or `*AADSTS700024*` | App reg / federated credential mismatch |
| SEC-05 | APP | `*ForbiddenByPolicy*` or `*"does not have secrets get permission"*` or `*"Caller is not authorized"*` | Key Vault access policy / RBAC |
| SEC-06 | ANY | `*FailedMount*` or `*"secrets-store"*` or `*CreateContainerConfigError*` or `*"couldn't find key"*` | CSI / K8s secret mount failure (events/CSI logs) |

## TLS / certificates — `playbooks/tls-certs.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| TLS-01 | APP | `*"PKIX path building failed"*` or `*"unable to find valid certification path"*` | Truststore missing CA |
| TLS-02 | APP | `*CertificateExpiredException*` or `*"certificate has expired"*` or `*NotAfter*` | Expired cert |
| TLS-03 | APP | `*SSLHandshakeException*` | Handshake failure (read cause) |
| TLS-04 | APP | `*"No subject alternative"*` or `*"doesn't match any of the subject alternative names"*` | Hostname/SAN mismatch |
| TLS-05 | APP | `*"Received fatal alert: certificate_unknown"*` or `*bad_certificate*` | Peer rejected our client cert |
| TLS-06 | APP | `*"protocol_version"*` or `*"No appropriate protocol"*` | TLS version mismatch |
| TLS-07 | SC/GW | `*TLS_error*` or `*CERTIFICATE_VERIFY_FAILED*` or `*CERTIFICATE_EXPIRED*` or `*WRONG_VERSION_NUMBER*` | Envoy TLS failure |
| TLS-08 | SC/GW | `*"failed to fetch secret"*` or `*"SDS"*` and `*error*` or `*"Failed to load certificate chain"*` | Gateway/sidecar cert not delivered |
| TLS-09 | ANY | `*"certificate expired"*` or `*"x509: certificate"*` | Go components (istiod, csi, cert-manager) |
| TLS-10 | ANY | `{ns}:cert-manager and (*"Failed to"* or *"Order failed"* or *"Challenge"* and *failed*)` | Renewal failed |

## Envoy / Istio proxy — `playbooks/envoy-istio.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| ENV-01 | SC | `*"Envoy proxy is NOT ready"*` | Sidecar not ready (xDS/config/cert) |
| ENV-02 | SC | `*"config not received from XDS server"*` or `*"connection to istiod"*` or `*"XDS proxy"*` and `*error*` | istiod unreachable |
| ENV-03 | SC | `*NACK*` or `*"gRPC config"*` and `*rejected*` | Bad EnvoyFilter / config rejected |
| ENV-04 | SC | `*"/app-health/"*` and (*" 503 "* or *" 500 "* or *refused*) | Readiness/liveness probe failing via pilot-agent |
| ENV-05 | SC | `*"Envoy exited"*` or `*"Envoy proxy exited"*` or `*"epoch 0 exited"*` | Sidecar crash |
| ENV-06 | SC | `*overflow*` or `*"upstream_rq_pending_overflow"*` | Circuit breaker |
| ENV-07 | ANY | `{app}:istiod and (*"Push debounce"* or *"Full push"* or *ERROR*)` | Mesh-wide config push / istiod trouble |
| ENV-08 | SC | `*"upstream connect error or disconnect/reset before headers"*` | Envoy-generated 503 body (logged by callers too) |

## HTTP clients / resilience — `playbooks/springboot.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| HTTP-01 | APP | `*"Connection refused"*` or `*ConnectException*` | Target down / port |
| HTTP-02 | APP | `*SocketTimeoutException*` or `*"Read timed out"*` or `*ReadTimeoutException*` | Slow dependency |
| HTTP-03 | APP | `*"connect timed out"*` or `*ConnectTimeoutException*` | Network / firewall / egress |
| HTTP-04 | APP | `*UnknownHostException*` or `*"Name or service not known"*` or `*"Failed to resolve"*` | DNS |
| HTTP-05 | APP | `*"Connection reset"*` or `*PrematureCloseException*` or `*"Connection prematurely closed"*` | Keepalive mismatch / peer RST |
| HTTP-06 | APP | `*FeignException*` or `*WebClientResponseException*` or `*HttpServerErrorException*` or `*HttpClientErrorException*` | Downstream HTTP error (code in message) |
| HTTP-07 | APP | `*CallNotPermittedException*` or `*"CircuitBreaker"* and *OPEN*` | Resilience4j breaker open |
| HTTP-08 | APP | `*BulkheadFullException*` or `*RejectedExecutionException*` | Thread pool / bulkhead saturated |
| HTTP-09 | APP | `*"TimeLimiter"*` or `*"did not complete within"*` | Resilience4j timeout |
| HTTP-10 | APP | `*"Pool exhausted"*` or `*PoolAcquireTimeoutException*` or `*"Timeout waiting for connection from pool"*` | HTTP client connection pool exhausted |
| HTTP-11 | APP | `*"401"* and (*Apigee* or *oauth*)` or `*invalid_token*` or `*"Jwt expired"*` | Token / auth to downstream |

## Databases / caches / queues — `playbooks/springboot.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| DB-01 | APP | `*"Connection is not available, request timed out"*` | Hikari pool exhausted (slow queries / leak / DB down) |
| DB-02 | APP | `*"Thread starvation or clock leap"*` | JVM pause / CPU throttling |
| DB-03 | APP | `*"Communications link failure"*` or `*"Connection refused"* and *jdbc*` or `*"The TCP/IP connection to the host"*` or `*IO Error*` | DB unreachable |
| DB-04 | APP | `*ORA-*` or `*SQLState*` or `*PSQLException*` or `*SQLServerException*` | DB-side error (code in message) |
| DB-05 | APP | `*deadlock*` or `*"lock wait timeout"*` or `*ORA-00060*` | Lock contention |
| DB-06 | APP | `*"Login failed"*` or `*"password authentication failed"*` or `*ORA-01017*` or `*ORA-28001*` | Credential rotated/expired |
| RD-01 | APP | `*RedisConnectionFailureException*` or `*RedisCommandTimeoutException*` or `*"Unable to connect to Redis"*` | Redis down/slow (Azure Cache 6380 TLS) |
| MQ-01 | APP | `*MQRC_*` or `*"Reason code 2009"*` or `*2059*` or `*2035*` or `*2538*` | IBM MQ: broken / QM unavailable / not authorized / host unreachable |
| MF-01 | APP | `*CICS*` or `*Hogan*` or `*mainframe*` and (*timeout* or *error* or *unavailable*) | Mainframe/Hogan path (adjust to catalog names) |
| SB-01 | APP | `*ServiceBusException*` or `*"amqp:"* and *error*` | Azure Service Bus |

## Kafka — `playbooks/kafka.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| KF-01 | APP | `*"could not be established. Broker may not be available"*` or `*"Bootstrap broker"* and *disconnected*` | Broker unreachable |
| KF-02 | APP | `*"Attempt to heartbeat failed since group is rebalancing"*` or `*"Revoking previously assigned partitions"*` or `*"partitions revoked"*` | Rebalance churn |
| KF-03 | APP | `*"poll timeout has expired"*` or `*"max.poll.interval.ms"*` or `*CommitFailedException*` | Consumer too slow → kicked from group |
| KF-04 | APP | `*SaslAuthenticationException*` or `*"Authentication failed"* and *kafka*` | SASL/creds (Event Hubs SAS) |
| KF-05 | APP | `*TopicAuthorizationException*` or `*GroupAuthorizationException*` | ACL |
| KF-06 | APP | `*"Expiring"* and *"record(s)"*` or `*"TimeoutException: Topic"*` or `*"not present in metadata"*` | Producer can't deliver / metadata |
| KF-07 | APP | `*NotLeaderOrFollower*` or `*LEADER_NOT_AVAILABLE*` or `*UNKNOWN_TOPIC_OR_PARTITION*` | Broker leadership / missing topic |
| KF-08 | APP | `*DeserializationException*` or `*SerializationException*` or `*"Error deserializing"*` | Poison message / schema change |
| KF-09 | APP | `*ListenerExecutionFailedException*` or `*"Backoff"* and *exhausted*` or `*".DLT"*` or `*"-dlt"*` | Listener failing → retries / DLT |
| KF-10 | APP | `*RecordTooLargeException*` or `*MESSAGE_TOO_LARGE*` | Payload size |
| KF-11 | APP | `*"Schema Registry"* and (*error* or *401* or *404*)` or `*RestClientException*` | Schema registry |
| KF-12 | APP | `*ProducerFencedException*` or `*InvalidProducerEpoch*` | Transactional producer fenced (dup instances) |

## Cassandra — `playbooks/cassandra.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| CS-01 | APP | `*AllNodesFailedException*` or `*NoNodeAvailableException*` or `*NoHostAvailableException*` | No reachable node |
| CS-02 | APP | `*DriverTimeoutException*` or `*OperationTimedOutException*` | Client-side timeout |
| CS-03 | APP | `*ReadTimeoutException*` or `*CassandraReadTimeoutException*` | Coordinator read timeout (replicas slow) |
| CS-04 | APP | `*WriteTimeoutException*` or `*CassandraWriteTimeoutException*` | Write timeout |
| CS-05 | APP | `*UnavailableException*` or `*"Not enough replicas available"*` | Replicas down for consistency level |
| CS-06 | APP | `*"AuthenticationException"* and *cassandra*` or `*"Provided username"*` | Creds |
| CS-07 | APP | `*InvalidQueryException*` or `*"unconfigured table"*` or `*"Keyspace"* and *"does not exist"*` | Schema / wrong keyspace (env mixup) |
| CS-08 | APP | `*BusyConnectionException*` or `*"Pool is busy"*` or `*BusyPoolException*` | Driver pool saturated |
| CS-09 | APP | `*"Error while opening new channel"*` or `*"Error connecting to Node"*` or `*"control connection"*` and *failed* | Connectivity / TLS to nodes |
| CS-10 | APP | `*OverloadedException*` or `*"Overloaded"*` | Cluster overloaded |
| CS-11 | ANY | `*"tombstone"*` or `*"Dropped mutations"*` or `*GCInspector*` | Server-side (if Cassandra logs indexed) |

## JVM / runtime / lifecycle — `references/k8s-from-logs.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| JVM-01 | APP | `*OutOfMemoryError*` | Heap / Metaspace / direct memory |
| JVM-02 | APP | `*"GC overhead limit"*` or `*"Pause Full"*` | GC thrash |
| JVM-03 | APP | `*StackOverflowError*` | Recursion bug |
| JVM-04 | APP | `*"Too many open files"*` | FD leak |
| LIF-01 | APP | `*"Starting"* and *Application*` or `*"Started"* and *"seconds (process running"*` | Start / restart marker |
| LIF-02 | APP | `*"Commencing graceful shutdown"*` or `*"Graceful shutdown complete"*` | SIGTERM (normal) |
| LIF-03 | APP | `*"Liveness state changed"*` or `*"Readiness state changed"*` or `*REFUSING_TRAFFIC*` | Boot availability state |
| LIF-04 | ANY | `*OOMKilled*` or `*OOMKilling*` or `*BackOff*` or `*Evicted*` or `*Unhealthy*` | K8s events (if shipped) |

## Front end / micro-apps — `playbooks/microapps-frontend.md`

| ID | Scope | KQL | Cause |
|---|---|---|---|
| FE-01 | SC/GW | `path : (*.js or *.css or *remoteEntry*) and response_code : 404` | Missing asset (version skew / CDN cache) |
| FE-02 | APP | `*"open()"* and *"failed (2: No such file"*` | NGINX in pod: file missing |
| FE-03 | APP | `*"upstream timed out"*` or `*"connect() failed"*` or `*"no live upstreams"*` | NGINX-in-pod proxy to API |
| FE-04 | SC/GW | `method : OPTIONS and response_code >= 400` | CORS preflight failing |
| FE-05 | APP | `*"Request Header Or Cookie Too Large"*` or `response_code : 431` | Oversized cookies |

## Platform / network

| ID | Scope | KQL | Cause |
|---|---|---|---|
| NET-01 | ANY | `{app}:coredns and (*SERVFAIL* or *"i/o timeout"*)` | Cluster DNS |
| NET-02 | APP | `*"No route to host"*` or `*EHOSTUNREACH*` | Network/NetworkPolicy/firewall |
| NET-03 | SC | `upstream_cluster : BlackHoleCluster` | Egress blocked (REGISTRY_ONLY) |

## Using the catalog

1. Build one `filters` agg with all IDs relevant to the app's dependencies (from catalog) plus CFG/SEC/TLS/JVM/LIF always.
2. Run for incident window and baseline window.
3. Rank: new > ratio ≥3× > absolute count. Ignore IDs with similar baseline rates.
4. For each surviving ID, fetch 3 samples (newest pod first, include `{pod}`, `{trace}`, `@timestamp`).
5. Earliest first-seen across surviving IDs = lead hypothesis.
