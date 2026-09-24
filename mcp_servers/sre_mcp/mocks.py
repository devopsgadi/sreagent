"""Fixture data for MOCK=true. One coherent scenario (payments-api bad deploy),
anchored to the current time so timelines always look fresh."""
from __future__ import annotations

import datetime as dt

from .common import iso, utcnow


def _t(minutes_ago: float) -> str:
    return iso(utcnow() - dt.timedelta(minutes=minutes_ago))


# ---------- ServiceNow ----------
def incidents() -> list[dict]:
    return [
        {"number": "INC0048213", "short_description": "payments-api returning 5xx for card payments",
         "priority": "2 - High", "state": "New", "service": "payments-api", "cmdb_ci": "payments-api",
         "assignment_group": "payments-platform", "opened_at": _t(25)},
        {"number": "INC0048190", "short_description": "Login latency above SLO in East region",
         "priority": "3 - Moderate", "state": "In Progress", "service": "login-service", "cmdb_ci": "login-service",
         "assignment_group": "identity", "opened_at": _t(140)},
        {"number": "INC0048177", "short_description": "Nightly statement batch job failed",
         "priority": "4 - Low", "state": "In Progress", "service": "statement-batch", "cmdb_ci": "statement-batch",
         "assignment_group": "core-banking-batch", "opened_at": _t(600)},
    ]


def incident(number: str) -> dict | None:
    for i in incidents():
        if i["number"] == number.upper():
            return {**i, "sys_id": f"mock-{i['number'].lower()}",
                    "description": i["short_description"] + ". Customers report failed card payments in mobile app.",
                    "work_notes": [], "caller": "NOC monitoring"}
    return None


def changes(service: str) -> list[dict]:
    if service != "payments-api":
        return []
    return [{"number": "CHG0031102", "short_description": "payments-api release v2.18.0",
             "state": "Implement", "type": "Standard", "start_date": _t(35), "end_date": _t(-25),
             "cmdb_ci": "payments-api", "assignment_group": "payments-platform"}]


def related_incidents(service: str) -> list[dict]:
    if service != "payments-api":
        return []
    return [{"number": "INC0047702", "short_description": "payments-api DB connection timeouts",
             "state": "Closed", "opened_at": _t(60 * 24 * 5), "close_notes": "Pool exhausted after config change; reverted."}]


# ---------- Datadog ----------
def monitors(service: str) -> list[dict]:
    if service != "payments-api":
        return []
    return [{"id": 991201, "name": "[payments-api] 5xx error rate > 5%", "overall_state": "Alert",
             "type": "query alert", "query": "sum(last_5m):... > 5", "state_changed_at": _t(28),
             "tags": ["service:payments-api", "env:prod", "team:payments-platform"]},
            {"id": 991207, "name": "[payments-api] p95 latency > 1.5s", "overall_state": "Warn",
             "type": "query alert", "query": "avg(last_5m):... > 1.5", "state_changed_at": _t(27),
             "tags": ["service:payments-api", "env:prod"]}]


def metric(service: str, name: str, minutes: int) -> dict:
    step = max(1, minutes // 24)
    pts = []
    for i in range(24, -1, -1):
        m = i * step
        if service == "payments-api" and name == "error_rate":
            v = 18.4 if m <= 28 else 0.3
        elif service == "payments-api" and name == "latency_p95":
            v = 1840.0 if m <= 28 else 210.0
        else:
            v = 0.2
        pts.append([_t(m), v])
    vals = [p[1] for p in pts]
    return {"metric": name, "points": pts, "min": min(vals), "max": max(vals), "last": vals[-1],
            "baseline": round(sum(vals[:6]) / 6, 2), "unit": "%" if name == "error_rate" else "ms"}


def dd_events(service: str) -> list[dict]:
    if service != "payments-api":
        return []
    return [{"title": "Deployment payments-api v2.18.0", "source": "gitlab", "date": _t(31)},
            {"title": "Monitor [payments-api] 5xx error rate triggered", "source": "monitor", "date": _t(28)}]


# ---------- Elastic ----------
def error_signatures(service: str) -> list[dict]:
    if service != "payments-api":
        return [{"error_type": "none", "count": 0}]
    return [{"error_type": "ConnectionPoolTimeoutException", "count": 2311,
             "sample": "HikariPool-1 - Connection is not available, request timed out after 3000ms (ledger-db)",
             "first_seen": _t(29), "last_seen": _t(0.5)},
            {"error_type": "UpstreamTimeout", "count": 412,
             "sample": "POST /v2/payments upstream ledger-client timed out after 5000ms",
             "first_seen": _t(28), "last_seen": _t(1)}]


def error_logs(service: str, limit: int) -> list[dict]:
    if service != "payments-api":
        return []
    rows = []
    for i in range(min(limit, 5)):
        rows.append({"@timestamp": _t(1 + i * 4), "level": "ERROR", "error_type": "ConnectionPoolTimeoutException",
                     "message": "HikariPool-1 - Connection is not available, request timed out after 3000ms. "
                                "card=4111 1111 1111 1111 customer=jane.doe@example.com",
                     "pod": f"payments-api-7f9c8d-{i}x", "trace_id": f"a1b2c3{i}"})
    return rows


def error_histogram(service: str, minutes: int) -> list[dict]:
    buckets = []
    for m in range(minutes, -1, -5):
        c = 0
        if service == "payments-api":
            c = 90 if m <= 30 else 2
        buckets.append({"time": _t(m), "errors": c})
    return buckets


# ---------- GitLab ----------
def deployments(service: str) -> list[dict]:
    if service != "payments-api":
        return []
    return [{"id": 88121, "ref": "v2.18.0", "sha": "9f3c2ab", "status": "success", "environment": "production",
             "created_at": _t(31), "user": "ci-bot", "merge_requests": [{"iid": 4412, "title": "Tune DB pool for new ledger client"}]},
            {"id": 88040, "ref": "v2.17.3", "sha": "4e1d0c7", "status": "success", "environment": "production",
             "created_at": _t(60 * 26), "user": "ci-bot", "merge_requests": [{"iid": 4390, "title": "Fix idempotency key TTL"}]}]


def mr_changes(service: str, iid: int) -> dict | None:
    if service != "payments-api" or iid != 4412:
        return None
    return {"iid": 4412, "title": "Tune DB pool for new ledger client", "author": "r.kumar", "merged_at": _t(40),
            "merge_commit_sha": "9f3c2ab", "web_url": "https://gitlab.internal/digital/payments-api/-/merge_requests/4412",
            "files": [{"path": "helm/values-prod.yaml",
                       "diff": "-  db:\n-    pool:\n-      maxSize: 50\n+  db:\n+    pool:\n+      maxSize: 10\n+      connectionTimeoutMs: 3000"},
                      {"path": "src/main/resources/application.yml",
                       "diff": "+ledger:\n+  client:\n+    timeoutMs: 5000"}]}


def failed_pipelines(service: str) -> list[dict]:
    return []
