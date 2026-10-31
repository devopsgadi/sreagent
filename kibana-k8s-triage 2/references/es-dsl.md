# Query library — DSL and ES|QL

`POST <index-pattern>/_search` (DSL) or `POST _query` (ES|QL, 8.11+). Replace fields per Step 0. Always set size and time range. Use `.keyword` when the field is `text`.

## Base filter
```json
{ "size": 0, "query": { "bool": { "filter": [
  { "range": { "@timestamp": { "gte": "FROM_UTC", "lte": "TO_UTC" } } },
  { "term": { "kubernetes.namespace": "NS" } },
  { "term": { "kubernetes.labels.app": "APP" } } ] } } }
```
SIDECAR: add `{ "term": { "kubernetes.container.name": "istio-proxy" } }`. APP_LOGS: same under `must_not`.

## §Scope — gateway errors by upstream, with timeline
```json
{ "size": 0,
  "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "FROM_UTC", "lte": "TO_UTC" } } },
    { "term": { "kubernetes.namespace": "istio-system" } },
    { "term": { "kubernetes.labels.app": "istio-ingressgateway" } },
    { "range": { "response_code": { "gte": 400 } } } ] } },
  "aggs": {
    "by_upstream": { "terms": { "field": "upstream_cluster", "size": 20 },
      "aggs": {
        "by_code": { "terms": { "field": "response_code" },
          "aggs": { "by_flag": { "terms": { "field": "response_flags" } },
                    "by_details": { "terms": { "field": "response_code_details", "size": 5 } } } },
        "paths": { "terms": { "field": "path", "size": 5 } },
        "first": { "min": { "field": "@timestamp" } },
        "last":  { "max": { "field": "@timestamp" } },
        "ids":   { "terms": { "field": "x_request_id", "size": 3 } } } },
    "timeline": { "date_histogram": { "field": "@timestamp", "fixed_interval": "1m" },
      "aggs": { "codes": { "terms": { "field": "response_code", "size": 5 } } } } } }
```
Run again with the baseline window. Error rate = errors / total (drop the `response_code` filter and use a `filter` sub-agg for the numerator).

## §Blast radius — cluster-wide 5xx by namespace / app / node
```json
{ "size": 0,
  "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "FROM_UTC", "lte": "TO_UTC" } } },
    { "range": { "response_code": { "gte": 500 } } } ] } },
  "aggs": {
    "ns":   { "terms": { "field": "kubernetes.namespace", "size": 30 },
      "aggs": { "app": { "terms": { "field": "kubernetes.labels.app", "size": 10 } } } },
    "node": { "terms": { "field": "kubernetes.node.name", "size": 20 } },
    "dep":  { "terms": { "field": "upstream_cluster", "size": 20 } } } }
```

## §Canary split
```json
"aggs": { "subset": { "terms": { "script": {
  "source": "def c = doc['upstream_cluster'].size()==0 ? '' : doc['upstream_cluster'].value; def p = c.splitOnToken('|'); return p.length>2 && p[2] != '' ? p[2] : 'none';" } },
  "aggs": { "codes": { "terms": { "field": "response_code" } } } } }
```
App logs: terms on `kubernetes.labels.version`.

## §Trace
```json
{ "size": 200, "sort": [{ "@timestamp": "asc" }],
  "_source": ["@timestamp","kubernetes.namespace","kubernetes.labels.app","kubernetes.pod.name","kubernetes.container.name","response_code","response_flags","response_code_details","upstream_cluster","duration","message","traceId"],
  "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "T-1h", "lte": "T+1h" } } } ],
    "should": [
      { "term": { "x_request_id": "REQUEST_ID" } },
      { "term": { "traceId": "TRACE_ID" } },
      { "match_phrase": { "message": "REQUEST_ID" } } ],
    "minimum_should_match": 1 } } }
```

### Bridge sidecar line → app logs (no request id in app)
```json
{ "size": 50, "sort": [{ "@timestamp": "asc" }],
  "query": { "bool": { "filter": [
    { "term": { "kubernetes.pod.name": "POD" } },
    { "range": { "@timestamp": { "gte": "T_MINUS_DURATION_MINUS_1S", "lte": "T_PLUS_1S" } } } ],
    "must_not": [ { "term": { "kubernetes.container.name": "istio-proxy" } } ] } } }
```

## §Gateway / inbound errors
```json
"filter": [ "...BASE...", { "term": { "kubernetes.container.name": "istio-proxy" } },
  { "prefix": { "upstream_cluster": "inbound|" } },
  { "range": { "response_code": { "gte": 400 } } } ]
"aggs": { "c": { "terms": { "field": "response_code" }, "aggs": {
  "f": { "terms": { "field": "response_flags" } },
  "d": { "terms": { "field": "response_code_details", "size": 5 } },
  "pod": { "terms": { "field": "kubernetes.pod.name", "size": 10 } } } } }
```
Errors on one pod only → that pod (OOM, bad node, stuck). All pods → app/dependency/config.

## §Outbound — dependency map with latency
```json
{ "size": 0,
  "query": { "bool": { "filter": [ "...BASE...",
    { "term": { "kubernetes.container.name": "istio-proxy" } },
    { "prefix": { "upstream_cluster": "outbound|" } } ] } },
  "aggs": { "dep": { "terms": { "field": "upstream_cluster", "size": 40 },
    "aggs": {
      "codes": { "terms": { "field": "response_code" } },
      "flags": { "terms": { "field": "response_flags" } },
      "details": { "terms": { "field": "response_code_details", "size": 5 } },
      "tfr": { "terms": { "field": "upstream_transport_failure_reason", "size": 3 } },
      "p95": { "percentiles": { "field": "duration", "percents": [50, 95, 99] } },
      "paths": { "terms": { "field": "path", "size": 5 } } } } } }
```
Include `PassthroughCluster` with sub-terms on `upstream_host` to see external IPs.

## §Signature scan (filters agg)
```json
{ "size": 0,
  "query": { "bool": { "filter": [ "...BASE + window..." ],
    "must_not": [ { "term": { "kubernetes.container.name": "istio-proxy" } } ] } },
  "aggs": { "sig": { "filters": { "filters": {
    "CFG-01": { "match_phrase": { "message": "APPLICATION FAILED TO START" } },
    "DB-01":  { "match_phrase": { "message": "Connection is not available, request timed out" } },
    "TLS-01": { "match_phrase": { "message": "PKIX path building failed" } },
    "KF-03":  { "match_phrase": { "message": "poll timeout has expired" } },
    "CS-05":  { "match_phrase": { "message": "Not enough replicas available" } }
  } },
  "aggs": { "first": { "min": { "field": "@timestamp" } },
            "pods": { "cardinality": { "field": "kubernetes.pod.name" } },
            "sample": { "top_hits": { "size": 2, "sort": [{ "@timestamp": "asc" }],
              "_source": ["@timestamp","kubernetes.pod.name","message","traceId"] } } } } } }
```
Prefer `match_phrase` over leading wildcards (cheaper, works on `text`). Also match `stack_trace` via `multi_match` type `phrase` on `["message","stack_trace","error.stack_trace"]`.

## §Baseline diff — what is new
```json
{ "size": 0,
  "query": { "bool": { "filter": [ "...BASE APP_LOGS...",
    { "range": { "@timestamp": { "gte": "FROM_UTC", "lte": "TO_UTC" } } } ] } },
  "aggs": {
    "new_terms": { "significant_text": { "field": "message", "size": 20,
      "filter_duplicate_text": true,
      "background_filter": { "bool": { "filter": [ "...BASE APP_LOGS...",
        { "range": { "@timestamp": { "gte": "BASELINE_FROM", "lte": "BASELINE_TO" } } } ] } } } },
    "new_loggers": { "significant_terms": { "field": "logger_name",
      "background_filter": { "range": { "@timestamp": { "gte": "BASELINE_FROM", "lte": "BASELINE_TO" } } } } } } }
```
Note: `background_filter` must be within the same query's index scope; query a pattern covering both windows and use `filter` agg wrappers if needed.

## §Patterns — collapse noise into templates
```json
{ "size": 0, "query": { "...APP_LOGS + window + level ERROR/WARN..." },
  "aggs": { "patterns": { "categorize_text": { "field": "message", "size": 25 },
    "aggs": { "first": { "min": { "field": "@timestamp" } },
              "pods": { "cardinality": { "field": "kubernetes.pod.name" } } } } } }
```
ES|QL (8.18+/9.x):
```
FROM logs-* | WHERE @timestamp >= "FROM" AND @timestamp <= "TO"
  AND kubernetes.namespace == "NS" AND kubernetes.labels.app == "APP"
  AND kubernetes.container.name != "istio-proxy"
| STATS n = COUNT(*), first = MIN(@timestamp) BY pattern = CATEGORIZE(message)
| SORT n DESC | LIMIT 25
```

## §Text access logs — parse at query time

ES|QL DISSECT (no ingest change):
```
FROM logs-* | WHERE @timestamp >= "FROM" AND @timestamp <= "TO"
  AND kubernetes.namespace == "NS" AND kubernetes.container.name == "istio-proxy"
  AND message LIKE "[*"
| DISSECT message """[%{ts}] "%{method} %{path} %{proto}" %{code} %{flags} %{details} %{term} "%{tfr}" %{rx} %{tx} %{dur} %{ust} "%{xff}" "%{ua}" "%{rid}" "%{authority}" "%{uhost}" %{ucluster} %{rest}"""
| EVAL code = TO_INTEGER(code), dur = TO_INTEGER(dur)
| WHERE code >= 500 OR code == 0
| STATS n = COUNT(*), p95 = PERCENTILE(dur, 95) BY ucluster, code, flags, details
| SORT n DESC | LIMIT 50
```
DSL runtime fields (pre-8.11):
```json
"runtime_mappings": {
  "rc": { "type": "long", "script": "def m = /\" (\\d{1,3}) ([A-Z,-]+) /.matcher(params._source.message); if (m.find()) emit(Long.parseLong(m.group(1)));" },
  "rf": { "type": "keyword", "script": "def m = /\" \\d{1,3} ([A-Z,-]+) /.matcher(params._source.message); if (m.find()) emit(m.group(1));" } }
```
Regex in Painless requires `script.painless.regex.enabled` (default `limited` is fine for this). Report "ingest pipeline needed" as a gap.

## §Pod lifecycle
```json
{ "size": 0,
  "query": { "bool": { "filter": [ "...BASE, window ±2h..." ] } },
  "aggs": { "pods": { "terms": { "field": "kubernetes.pod.name", "size": 100, "order": { "first": "asc" } },
    "aggs": {
      "image": { "terms": { "field": "container.image.name", "size": 3 } },
      "version": { "terms": { "field": "kubernetes.labels.version", "size": 2 } },
      "node":  { "terms": { "field": "kubernetes.node.name", "size": 1 } },
      "first": { "min": { "field": "@timestamp" } },
      "last":  { "max": { "field": "@timestamp" } },
      "starts": { "filter": { "match_phrase": { "message": "Started" } } },
      "graceful": { "filter": { "match_phrase": { "message": "Commencing graceful shutdown" } } },
      "oom": { "filter": { "match_phrase": { "message": "OutOfMemoryError" } } } } } } }
```
ReplicaSet hash via ES|QL:
```
| DISSECT kubernetes.pod.name "%{prefix}-%{rs}-%{suffix}"
| STATS first = MIN(@timestamp), last = MAX(@timestamp), pods = COUNT_DISTINCT(kubernetes.pod.name) BY rs, container.image.name
| SORT first
```
(If the deployment name contains dashes, take the last two tokens: rs = second-last.)

## §Last lines of a dead pod
```json
{ "size": 60, "sort": [{ "@timestamp": "desc" }],
  "query": { "bool": { "filter": [ { "term": { "kubernetes.pod.name": "POD" } } ],
    "must_not": [ { "term": { "kubernetes.container.name": "istio-proxy" } } ] } } }
```

## §K8s events (if shipped)
```json
{ "size": 50, "sort": [{ "@timestamp": "asc" }],
  "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "FROM-1h", "lte": "TO" } } },
    { "term": { "kubernetes.event.involved_object.namespace": "NS" } },
    { "prefix": { "kubernetes.event.involved_object.name": "APP" } } ],
    "should": [ { "term": { "kubernetes.event.type": "Warning" } },
                { "terms": { "kubernetes.event.reason": ["ScalingReplicaSet","Killing","Pulled","Created","Started","SuccessfulCreate","SuccessfulDelete"] } } ],
    "minimum_should_match": 1 } },
  "aggs": { "reasons": { "terms": { "field": "kubernetes.event.reason", "size": 20 } } } }
```

## §Shipper / retention sanity
```json
{ "size": 0, "query": { "range": { "@timestamp": { "gte": "FROM", "lte": "TO" } } },
  "aggs": { "per_min": { "date_histogram": { "field": "@timestamp", "fixed_interval": "1m" } },
            "ns": { "terms": { "field": "kubernetes.namespace", "size": 50 } } } }
```
A gap across all namespaces = shipper/ingest outage, not an app silence.
