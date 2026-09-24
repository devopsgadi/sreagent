"""Kibana / Elasticsearch MCP server. Queries Elasticsearch directly and returns
aggregated, redacted results (never raw hit dumps)."""
from __future__ import annotations

import os
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from . import mocks
from .common import MOCK, clean, http_client, resolve_service, run

mcp = FastMCP("kibana", stateless_http=True)

LEVEL = os.getenv("ES_LEVEL_FIELD", "log.level")
ERR_TYPE = os.getenv("ES_ERROR_TYPE_FIELD", "error.type")
MSG = os.getenv("ES_MESSAGE_FIELD", "message")
ERROR_LEVELS = ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]


def _client():
    headers = {"Content-Type": "application/json"}
    if os.getenv("ES_API_KEY"):
        headers["Authorization"] = f"ApiKey {os.environ['ES_API_KEY']}"
        return http_client(os.environ["ES_URL"], headers)
    return http_client(os.environ["ES_URL"], headers, auth=(os.environ["ES_USER"], os.environ["ES_PASSWORD"]))


def _filter(svc: dict, minutes: int, extra_query: str | None = None) -> dict:
    must = [
        {"term": {svc.get("kibana_service_field", "service.name"): svc["name"]}},
        {"terms": {LEVEL: ERROR_LEVELS}},
        {"range": {"@timestamp": {"gte": f"now-{int(minutes)}m"}}},
    ]
    if extra_query:
        must.append({"query_string": {"query": extra_query, "default_field": MSG}})
    return {"bool": {"filter": must}}


def _search(svc: dict, body: dict) -> dict:
    with _client() as c:
        r = c.post(f"/{svc['kibana_index']}/_search", json=body)
        r.raise_for_status()
        return r.json()


def _discover_url(svc: dict, minutes: int) -> str | None:
    base = os.getenv("KIBANA_URL")
    if not base:
        return None
    q = quote(f'{svc.get("kibana_service_field", "service.name")}:"{svc["name"]}" and {LEVEL}:(error or ERROR)')
    return f"{base.rstrip('/')}/app/discover#/?_g=(time:(from:now-{minutes}m,to:now))&_a=(query:(language:kuery,query:'{q}'))"


@mcp.tool()
def top_error_signatures(service: str, minutes: int = 60, size: int = 10) -> dict:
    """Group error logs by error type: count, first/last seen, one sample message each.
    Start here; it is the cheapest way to see what is failing."""
    svc = resolve_service(service)
    if MOCK:
        return clean({"service": svc["name"], "window_minutes": minutes, "signatures": mocks.error_signatures(svc["name"]),
                      "discover_url": "https://kibana.internal/app/discover (mock)"})
    body = {"size": 0, "query": _filter(svc, minutes), "aggs": {"sig": {
        "terms": {"field": ERR_TYPE, "size": size, "missing": "unknown"},
        "aggs": {"first": {"min": {"field": "@timestamp"}}, "last": {"max": {"field": "@timestamp"}},
                 "sample": {"top_hits": {"size": 1, "_source": [MSG]}}}}}}
    data = _search(svc, body)
    sigs = []
    for b in data["aggregations"]["sig"]["buckets"]:
        hit = (b["sample"]["hits"]["hits"] or [{}])[0].get("_source", {})
        sigs.append({"error_type": b["key"], "count": b["doc_count"], "first_seen": b["first"].get("value_as_string"),
                     "last_seen": b["last"].get("value_as_string"), "sample": hit.get(MSG, "")})
    return clean({"service": svc["name"], "window_minutes": minutes, "signatures": sigs,
                  "discover_url": _discover_url(svc, minutes)})


@mcp.tool()
def search_errors(service: str, minutes: int = 60, query: str | None = None, limit: int = 20) -> list[dict]:
    """Most recent error log lines (redacted), optionally filtered by a Lucene query string,
    e.g. query='ConnectionPoolTimeout'."""
    svc = resolve_service(service)
    limit = min(limit, 50)
    if MOCK:
        return clean(mocks.error_logs(svc["name"], limit))
    body = {"size": limit, "sort": [{"@timestamp": "desc"}], "query": _filter(svc, minutes, query),
            "_source": ["@timestamp", MSG, LEVEL, ERR_TYPE, "kubernetes.pod.name", "trace.id"]}
    rows = []
    for h in _search(svc, body)["hits"]["hits"]:
        s = h["_source"]
        get = lambda path: _dig(s, path)  # noqa: E731
        rows.append({"@timestamp": s.get("@timestamp"), "level": get(LEVEL), "error_type": get(ERR_TYPE),
                     "message": get(MSG), "pod": get("kubernetes.pod.name"), "trace_id": get("trace.id")})
    return clean(rows)


@mcp.tool()
def error_histogram(service: str, minutes: int = 120, interval: str = "5m") -> dict:
    """Error count per time bucket. Use it to find exactly when errors started."""
    svc = resolve_service(service)
    if MOCK:
        buckets = mocks.error_histogram(svc["name"], minutes)
    else:
        body = {"size": 0, "query": _filter(svc, minutes),
                "aggs": {"h": {"date_histogram": {"field": "@timestamp", "fixed_interval": interval}}}}
        buckets = [{"time": b["key_as_string"], "errors": b["doc_count"]}
                   for b in _search(svc, body)["aggregations"]["h"]["buckets"]]
    onset = None
    if buckets:
        base = sorted(b["errors"] for b in buckets)[len(buckets) // 2]
        for b in buckets:
            if b["errors"] > max(10, base * 5):
                onset = b["time"]
                break
    return clean({"service": svc["name"], "interval": interval, "buckets": buckets, "estimated_onset": onset})


def _dig(src: dict, path: str):
    if path in src:
        return src[path]
    cur = src
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


if __name__ == "__main__":
    run(mcp, 8103)
