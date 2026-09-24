"""Datadog MCP server: monitors, metric queries, events."""
from __future__ import annotations

import datetime as dt
import os
import time

from mcp.server.fastmcp import FastMCP

from . import mocks
from .common import MOCK, clean, http_client, iso, resolve_service, run

mcp = FastMCP("datadog", stateless_http=True)

# Named metric templates so the LLM never has to write Datadog query syntax.
METRICS = {
    "error_rate": "(sum:trace.http.request.errors{{service:{s},env:{e}}}.as_count() / "
                  "sum:trace.http.request.hits{{service:{s},env:{e}}}.as_count()) * 100",
    "request_rate": "sum:trace.http.request.hits{{service:{s},env:{e}}}.as_rate()",
    "latency_p95": "p95:trace.http.request{{service:{s},env:{e}}}",
    "pod_restarts": "sum:kubernetes.containers.restarts{{kube_deployment:{s}}}",
    "cpu": "avg:kubernetes.cpu.usage.total{{kube_deployment:{s}}}",
    "memory": "avg:kubernetes.memory.usage{{kube_deployment:{s}}}",
}


def _client():
    site = os.getenv("DD_SITE", "datadoghq.com")
    return http_client(f"https://api.{site}", {
        "DD-API-KEY": os.environ["DD_API_KEY"], "DD-APPLICATION-KEY": os.environ["DD_APP_KEY"],
        "Accept": "application/json"})


@mcp.tool()
def get_active_monitors(service: str) -> list[dict]:
    """Monitors tagged with the service that are currently in Alert, Warn or No Data,
    with when they changed state."""
    svc = resolve_service(service)
    if MOCK:
        return clean(mocks.monitors(svc["name"]))
    with _client() as c:
        r = c.get("/api/v1/monitor", params={"monitor_tags": f"service:{svc['datadog_service']}",
                                             "group_states": "alert,warn,no data"})
        r.raise_for_status()
    out = []
    for m in r.json():
        if m.get("overall_state") in ("Alert", "Warn", "No Data"):
            out.append({"id": m["id"], "name": m["name"], "overall_state": m["overall_state"],
                        "type": m.get("type"), "query": m.get("query"),
                        "state_changed_at": m.get("overall_state_modified"), "tags": m.get("tags", [])})
    return clean(out)


@mcp.tool()
def query_metric(service: str, metric: str = "error_rate", minutes: int = 120) -> dict:
    """Timeseries summary for a named metric: error_rate, request_rate, latency_p95,
    pod_restarts, cpu, memory. Returns downsampled points plus min/max/last and a baseline
    (average of the first quarter of the window) so you can spot the onset."""
    svc = resolve_service(service)
    if metric not in METRICS:
        return {"error": f"Unknown metric '{metric}'. Use one of: {', '.join(METRICS)}"}
    if MOCK:
        return clean(mocks.metric(svc["name"], metric, minutes))
    q = METRICS[metric].format(s=svc["datadog_service"], e=svc.get("datadog_env", "prod"))
    now = int(time.time())
    with _client() as c:
        r = c.get("/api/v1/query", params={"from": now - minutes * 60, "to": now, "query": q})
        r.raise_for_status()
    series = r.json().get("series", [])
    if not series:
        return {"metric": metric, "points": [], "note": "no data"}
    raw = [(p[0], p[1]) for p in series[0]["pointlist"] if p[1] is not None]
    step = max(1, len(raw) // 30)
    pts = [[iso(dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)), round(v, 3)]
           for ts, v in raw[::step]]
    vals = [v for _, v in raw] or [0]
    q_len = max(1, len(vals) // 4)
    return {"metric": metric, "points": pts, "min": min(vals), "max": max(vals), "last": vals[-1],
            "baseline": round(sum(vals[:q_len]) / q_len, 3), "query": q}


@mcp.tool()
def get_events(service: str, minutes: int = 240) -> list[dict]:
    """Datadog events tagged with the service (deploys, monitor transitions, config changes)."""
    svc = resolve_service(service)
    if MOCK:
        return clean(mocks.dd_events(svc["name"]))
    now = int(time.time())
    with _client() as c:
        r = c.get("/api/v1/events", params={"start": now - minutes * 60, "end": now,
                                            "tags": f"service:{svc['datadog_service']}"})
        r.raise_for_status()
    return clean([{"title": e.get("title"), "source": e.get("source_type_name"),
                   "date": iso(dt.datetime.fromtimestamp(e["date_happened"], dt.timezone.utc)),
                   "text": e.get("text", "")} for e in r.json().get("events", [])][:30])


if __name__ == "__main__":
    run(mcp, 8102)
