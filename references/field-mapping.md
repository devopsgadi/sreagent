# Field mapping

Fetch one doc first:
- KQL: `kubernetes.namespace : "NS"` (or `kubernetes.namespace_name`, `k8s.namespace.name`), latest 1 hit
- ES API: `GET <index>/_search?size=1&q=NS&sort=@timestamp:desc`
- Or `GET <index>/_mapping/field/kubernetes.*`

## Kubernetes metadata variants

| Placeholder | Filebeat / Elastic Agent (ECS) | Fluent Bit | Fluentd (k8s metadata filter) | OTel |
|---|---|---|---|---|
| {ns} | kubernetes.namespace | kubernetes.namespace_name | kubernetes.namespace_name | k8s.namespace.name |
| {app} | kubernetes.labels.app | kubernetes.labels.app | kubernetes.labels.app | k8s.pod.labels.app |
| {pod} | kubernetes.pod.name | kubernetes.pod_name | kubernetes.pod_name | k8s.pod.name |
| {container} | kubernetes.container.name | kubernetes.container_name | kubernetes.container_name | k8s.container.name |
| {image} | container.image.name | kubernetes.container_image | kubernetes.container_image | container.image.name |
| {msg} | message | log | log / message | body |

Label keys with dots or slashes (`app.kubernetes.io/name`) become `kubernetes.labels.app_kubernetes_io/name` in ECS (dots → underscores). Check the doc.

App JSON logs may be nested under `json.*`, `log.*`, or the root. Spring Boot with logstash-encoder typically gives `level`, `logger_name`, `stack_trace`, `traceId`.

## Istio access log: JSON vs text

**JSON** (`meshConfig.accessLogEncoding: JSON`): fields arrive structured, possibly under a prefix such as `json.` or `istio.`. Use them directly.

**TEXT (default)**: a single line in {msg}, like:
```
[2026-10-06T10:01:02.123Z] "GET /api/v1/orders HTTP/1.1" 502 UF upstream_reset_before_response_started{...} - "-" 0 87 3 - "10.0.0.1" "curl/8" "abc-123-req-id" "orders.svc" "10.1.2.3:8080" outbound|8080||orders.ns.svc.cluster.local ...
```
Positional order: start_time, method/path/protocol, response_code, response_flags, response_code_details, connection_termination_details, upstream_transport_failure_reason, bytes_received, bytes_sent, duration, upstream_service_time, x_forwarded_for, user_agent, x_request_id, authority, upstream_host, upstream_cluster, ...

Text fallbacks:
- outbound: `{msg} : *outbound|*`
- inbound: `{msg} : *inbound|*`
- request id: `{msg} : *REQUEST_ID*`
- 502 with flag: `{msg} : *"\" 502 UF"*`. This is fragile; prefer a runtime field or a grok/dissect ingest pipeline, and flag this as a gap in the report.
