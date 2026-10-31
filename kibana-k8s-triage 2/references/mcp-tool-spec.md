# kibana MCP server — tool contracts

Contracts for the tools the skill expects. All tools are read-only, take catalog names, resolve field names from a cached `discover_fields` result per index pattern, enforce a max window (default 6h) and `size` caps, and return **aggregations + ≤5 sample docs**, never raw dumps. Every response includes `query` (the exact DSL/ES|QL run) so the agent can cite it.

Common params: `env`, `ns`, `app`, `from`, `to` (UTC ISO), optional `baseline_from`/`baseline_to` (default: same window −24h), `index_pattern` (resolved from env/PCI if omitted).

Common result envelope:
```json
{ "query": {...}, "window": {...}, "baseline": {...}, "field_map": {...},
  "data": {...}, "samples": [ {"ts":"","pod":"","container":"","request_id":"","trace_id":"","msg":""} ],
  "gaps": ["access logs unparsed text", "no k8s events index"] }
```

| Tool | Params (extra) | Returns |
|---|---|---|
| `list_indices` | `env` | patterns, retention, which datasets exist (app, istio, events, istiod, edge, apigee, cassandra, audit) |
| `discover_fields` | `ns`, `app` | placeholder → field map, access log JSON/TEXT, trace field present, field types |
| `error_heatmap` | `scope: gateway|namespace|cluster` | per-minute counts by code; top ns/app/node/upstream; incident vs baseline rate |
| `gateway_errors` | `svc?`, `host?`, `min_code` | upstream × code × flags × details; paths; first/last; sample request ids; subset split |
| `trace_lookup` | `request_id?`, `trace_id?` | ordered hops (gateway, sidecar in/out, app), last hop, verdict per Step 2 table |
| `sidecar_inbound_errors` | — | code × flags × details × pod; per-pod error share |
| `istio_outbound_failures` | — | per upstream_cluster: codes, flags, details, transport failure reason, p50/p95/p99 duration, TCP deps |
| `signature_scan` | `families?: [CFG,SEC,TLS,ENV,HTTP,DB,KF,CS,JVM,LIF,FE,NET]` | per signature ID: incident count, baseline count, ratio, first seen, pods, 2 samples. Sorted new > ratio |
| `config_secret_signatures` | — | CFG + SEC subset of `signature_scan` with Boot `Description/Action` block extracted |
| `baseline_diff` | `field: message|logger|exception` | significant terms/text with scores and samples |
| `log_patterns` | `level?` | categorize_text patterns with counts, first seen, pods; incident vs baseline |
| `pod_lifecycle` | `widen: 2h` | per RS hash and pod: image, version label, node, first/last, starts, graceful, OOM markers; inferred events (rollout, restart, crashloop, node loss) |
| `k8s_warning_events` | — | events by reason (if index exists) else `gaps` |
| `tls_failures` | `target_host?` | TLS signatures across app + sidecar + gateway, extracted hosts, NotAfter dates if present |
| `kafka_health` | `topic?`, `group?` | rebalance timeline, poll timeouts, auth/connectivity, stuck offsets (same offset repeated), DLT counts |
| `cassandra_health` | `keyspace?` | error class split, coordinator IPs, consistency levels, slow statements |
| `edge_lookup` | `host`, `path?`, `client_ip?` | NGINX Plus / F5 / Apigee lines matching window; edge error text; last hop |
| `istio_control_plane` | — | istiod errors, push timestamps, NACKs, CA errors in window |
| `timeline` | `ns`, `app`, deps from catalog | merged first-seen of every anomaly (deploy, restart, signature, flag, dependency) sorted ascending — the agent's root-cause candidate list |
| `sanity_checks` | — | shipper gaps, other namespaces present, label alternatives that match, access logging present |

## Implementation notes
- Run incident and baseline as one `_msearch` to halve latency.
- Cache `discover_fields` per (index pattern, ns) for 1h.
- Text access logs: implement parsing once with ES|QL DISSECT (8.11+) or runtime_mappings, behind the same tool output shape so the agent never sees the difference (but surface the gap).
- Signature catalog lives as YAML in the server repo (`signatures.yaml`: id, family, scope, kql, phrase[], playbook) generated from `references/signature-catalog.md`; one source of truth for agent and server.
- PII: strip `Authorization`, cookies, account numbers from samples before returning (PCI envs).
- Rate-limit per incident; never run unbounded wildcards on `message` over >6h — use `match_phrase`.
