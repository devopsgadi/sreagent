# Elasticsearch DSL equivalents

Use when calling `POST <index-pattern>/_search` directly (MCP/API). Replace field names per Step 0. Always set `"size"` and a time range.

## Common time + base filter
```json
{
  "size": 50,
  "sort": [{ "@timestamp": "asc" }],
  "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "FROM_UTC", "lte": "TO_UTC" } } },
    { "term": { "kubernetes.namespace": "NS" } },
    { "term": { "kubernetes.labels.app": "APP" } }
  ] } }
}
```
Add `{ "term": { "kubernetes.container.name": "istio-proxy" } }` for SIDECAR, or put it under `must_not` for APP_LOGS. Use `.keyword` sub-fields if the field is `text`.

## Gateway 5xx for a service, aggregated
```json
{
  "size": 5,
  "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "FROM_UTC", "lte": "TO_UTC" } } },
    { "term": { "kubernetes.namespace": "istio-system" } },
    { "term": { "kubernetes.labels.app": "istio-ingressgateway" } },
    { "wildcard": { "upstream_cluster": "*SVC.NS.svc.cluster.local*" } },
    { "range": { "response_code": { "gte": 500 } } }
  ] } },
  "aggs": {
    "by_code": { "terms": { "field": "response_code" },
      "aggs": { "by_flag": { "terms": { "field": "response_flags" } } } },
    "by_path": { "terms": { "field": "path", "size": 10 } },
    "first_seen": { "min": { "field": "@timestamp" } },
    "last_seen":  { "max": { "field": "@timestamp" } },
    "sample_ids": { "terms": { "field": "x_request_id", "size": 3 } }
  }
}
```

## Request trace
```json
{ "size": 100, "sort": [{ "@timestamp": "asc" }],
  "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "FROM_UTC-1h", "lte": "TO_UTC+1h" } } },
    { "term": { "x_request_id": "REQUEST_ID" } } ] } } }
```
If not structured: `{ "match_phrase": { "message": "REQUEST_ID" } }`.

## Outbound dependencies
```json
{ "size": 0,
  "query": { "bool": { "filter": [ "...BASE...",
    { "term": { "kubernetes.container.name": "istio-proxy" } },
    { "prefix": { "upstream_cluster": "outbound|" } } ] } },
  "aggs": { "by_host": { "terms": { "field": "authority", "size": 30 },
    "aggs": {
      "codes": { "terms": { "field": "response_code" } },
      "paths": { "terms": { "field": "path", "size": 10 } } } } } }
```

## Pod lifecycle / deploy correlation
```json
{ "size": 0,
  "query": { "bool": { "filter": [ "...BASE with window widened to ±2h..." ] } },
  "aggs": { "pods": { "terms": { "field": "kubernetes.pod.name", "size": 50 },
    "aggs": {
      "image": { "terms": { "field": "container.image.name", "size": 3 } },
      "first": { "min": { "field": "@timestamp" } },
      "last":  { "max": { "field": "@timestamp" } } } } } }
```

## Last lines of a dead pod
```json
{ "size": 50, "sort": [{ "@timestamp": "desc" }],
  "query": { "bool": {
    "filter": [ { "term": { "kubernetes.pod.name": "POD" } } ],
    "must_not": [ { "term": { "kubernetes.container.name": "istio-proxy" } } ] } } }
```

## Error / secret signatures
```json
{ "bool": { "should": [
  { "terms": { "log.level": ["ERROR", "FATAL"] } },
  { "query_string": { "default_field": "message",
    "query": "*secret* OR *keyvault* OR *credential* OR \"Could not resolve placeholder\" OR BeanCreationException OR \"APPLICATION FAILED TO START\" OR Unauthorized OR Forbidden" } }
], "minimum_should_match": 1 } }
```
