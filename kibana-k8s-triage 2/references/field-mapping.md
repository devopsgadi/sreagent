# Field mapping

## Discover

- KQL: `kubernetes.namespace : "NS"` (or `kubernetes.namespace_name`, `k8s.namespace.name`), newest 1 hit, once for the app container and once for `istio-proxy`.
- ES: `GET <index>/_search?size=1&q=NS&sort=@timestamp:desc`
- Mapping: `GET <index>/_mapping/field/kubernetes.*,response_*,upstream_*,log.*,level,traceId`
- Field caps across patterns: `GET <pattern>/_field_caps?fields=response_code,response_flags,traceId,kubernetes.*`

Check each field's type: `text` fields need `.keyword` for `term`/`terms`.

## Kubernetes metadata

| Placeholder | Filebeat / Elastic Agent (ECS) | Fluent Bit | Fluentd | OTel |
|---|---|---|---|---|
| {ns} | kubernetes.namespace | kubernetes.namespace_name | kubernetes.namespace_name | k8s.namespace.name |
| {app} | kubernetes.labels.app | kubernetes.labels.app | kubernetes.labels.app | k8s.pod.labels.app |
| {version} | kubernetes.labels.version | kubernetes.labels.version | kubernetes.labels.version | k8s.pod.labels.version |
| {pod} | kubernetes.pod.name | kubernetes.pod_name | kubernetes.pod_name | k8s.pod.name |
| {container} | kubernetes.container.name | kubernetes.container_name | kubernetes.container_name | k8s.container.name |
| {image} | container.image.name | kubernetes.container_image | kubernetes.container_image | container.image.name |
| {node} | kubernetes.node.name | kubernetes.host | kubernetes.host | k8s.node.name |
| {pod_ip} | kubernetes.pod.ip | — | — | k8s.pod.ip |
| {cluster} | orchestrator.cluster.name | cluster / custom | custom | k8s.cluster.name |
| {msg} | message | log | log / message | body |
| {stream} | stream | stream | stream | log.iostream |

ECS turns dots in label keys into underscores: `app.kubernetes.io/name` → `kubernetes.labels.app_kubernetes_io/name`.
ReplicaSet owner (if present): `kubernetes.replicaset.name` (ECS) — otherwise derive from pod name.

## App logs

| Placeholder | logstash-logback-encoder | ECS logging (co.elastic) | Plain text |
|---|---|---|---|
| {level} | level | log.level | parse from {msg} |
| {logger} | logger_name | log.logger | parse |
| {thread} | thread_name | process.thread.name | parse |
| {trace} | traceId / trace_id | trace.id | `[app,traceId,spanId]` in line |
| {span} | spanId | span.id | — |
| {stack} | stack_trace | error.stack_trace | multiline in {msg} |
| {exc} | — | error.type | first line of stack |

App JSON may be nested under `json.*`, `app.*`, `log.*`, or the root. Spring Boot 3 + Micrometer Tracing puts `traceId`/`spanId` in MDC; Boot 2 + Sleuth uses the same names.

Plain text Spring Boot default line:
```
2026-10-31T10:01:02.123Z ERROR 1 --- [app] [nio-8080-exec-3] [traceId-spanId] c.x.OrderService : message
```

## Istio access log — JSON

`meshConfig.accessLogEncoding: JSON` → fields structured, maybe under `json.`, `istio.`, or `envoy.` prefix. Common names: `response_code`, `response_flags`, `response_code_details`, `connection_termination_details`, `upstream_transport_failure_reason`, `upstream_cluster`, `upstream_host`, `upstream_local_address`, `downstream_local_address`, `downstream_remote_address`, `requested_server_name`, `authority`, `path`, `method`, `protocol`, `x_forwarded_for`, `user_agent`, `request_id` or `x_request_id`, `duration`, `upstream_service_time`, `bytes_received`, `bytes_sent`, `route_name`, `start_time`.

## Istio access log — TEXT (default format)

```
[START_TIME] "METHOD PATH PROTOCOL" RESPONSE_CODE RESPONSE_FLAGS RESPONSE_CODE_DETAILS CONNECTION_TERMINATION_DETAILS "UPSTREAM_TRANSPORT_FAILURE_REASON" BYTES_RECEIVED BYTES_SENT DURATION UPSTREAM_SERVICE_TIME "X_FORWARDED_FOR" "USER_AGENT" "X_REQUEST_ID" "AUTHORITY" "UPSTREAM_HOST" UPSTREAM_CLUSTER UPSTREAM_LOCAL_ADDRESS DOWNSTREAM_LOCAL_ADDRESS DOWNSTREAM_REMOTE_ADDRESS REQUESTED_SERVER_NAME ROUTE_NAME
```
Example:
```
[2026-10-06T10:01:02.123Z] "GET /api/v1/orders HTTP/1.1" 502 UF upstream_reset_before_response_started{connection_failure} - "-" 0 87 3 - "10.0.0.1" "curl/8" "abc-123" "orders.ns.svc" "10.1.2.3:8080" outbound|8080||orders.ns.svc.cluster.local 10.1.9.9:41234 10.1.2.3:8080 10.1.9.9:41230 - default
```
TCP connections (Kafka, Cassandra, DB) log as `"- - -" 0 FLAGS ...` with no method/path.

Parse at query time (no ingest change needed) — see `es-dsl.md` §Text access logs. Wildcard fallbacks in KQL:
- outbound: `{msg} : *outbound|*` · inbound: `{msg} : *inbound|*`
- request id: `{msg} : *REQUEST_ID*`
- 502 with flag: `{msg} : *"\" 502 UF"*` — fragile; prefer ES|QL DISSECT.

## upstream_cluster anatomy

```
outbound|8080|next|orders.ns.svc.cluster.local   → port, subset (canary), host
inbound|8080||                                   → into local app container
outbound|443||login.microsoftonline.com          → ServiceEntry / external
PassthroughCluster                               → destination not in registry (ALLOW_ANY)
BlackHoleCluster                                 → destination blocked (REGISTRY_ONLY)
InboundPassthroughCluster(Ipv4)                  → inbound to a port not declared on the Service
```
Extract subset with ES|QL `DISSECT upstream_cluster "%{dir}|%{port}|%{subset}|%{host}"`.

## Other indices worth discovering

| Data | Typical index / dataset | Use |
|---|---|---|
| K8s events | `logs-kubernetes.events*`, `k8s-events-*`, `kubernetes.event.*` fields | OOMKilling, BackOff, FailedMount, Unhealthy, Evicted, ScalingReplicaSet |
| istiod | `{ns}:istio-system and {app}:istiod` | xDS pushes, NACKs, cert signing (CA) errors |
| cert-manager | `{ns}:cert-manager` | issuance/renewal failures |
| CSI Secret Store / Key Vault provider | `{ns}:kube-system and {app}:*secrets-store*` | mount failures |
| CoreDNS | `{app}:coredns` / `kube-dns` | NXDOMAIN, SERVFAIL, timeouts |
| Ingress NGINX / NGINX Plus / F5 | edge indices | pre-mesh failures |
| Apigee | Apigee analytics / message logging export | proxy vs target errors |
| Audit (AKS diagnostic / on-prem) | `kube-audit*` | who changed what (deployments, configmaps) |
