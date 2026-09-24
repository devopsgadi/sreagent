"""ServiceNow MCP server (Table API). Read tools + one gated write tool (action_*)."""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from . import mocks
from .common import MOCK, clean, http_client, resolve_service, run

mcp = FastMCP("servicenow", stateless_http=True)

FIELDS = ("number,sys_id,short_description,description,priority,state,cmdb_ci,assignment_group,"
          "opened_at,resolved_at,caller_id,category,subcategory,impact,urgency")


def _client():
    url = os.environ["SNOW_URL"]
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if os.getenv("SNOW_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['SNOW_TOKEN']}"
        return http_client(url, headers)
    return http_client(url, headers, auth=(os.environ["SNOW_USER"], os.environ["SNOW_PASSWORD"]))


def _table(table: str, query: str, fields: str, limit: int) -> list[dict]:
    with _client() as c:
        r = c.get(f"/api/now/table/{table}", params={
            "sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": limit,
            "sysparm_display_value": "true", "sysparm_exclude_reference_link": "true"})
        r.raise_for_status()
        return r.json().get("result", [])


def _service_for_ci(ci: str) -> str | None:
    try:
        return resolve_service(ci)["name"]
    except ValueError:
        return None


@mcp.tool()
def get_incident(number: str) -> dict:
    """Get one incident by number (e.g. INC0048213): description, priority, state, CI,
    assignment group, opened time, and the mapped `service` name to use with other tools."""
    if MOCK:
        inc = mocks.incident(number)
        return clean(inc or {"error": f"Incident {number} not found"})
    rows = _table("incident", f"number={number.upper()}", FIELDS, 1)
    if not rows:
        return {"error": f"Incident {number} not found"}
    inc = rows[0]
    inc["service"] = _service_for_ci(inc.get("cmdb_ci", ""))
    return clean(inc)


@mcp.tool()
def list_open_incidents(max_priority: int = 3, limit: int = 25) -> list[dict]:
    """List active incidents at or above a priority (1 = highest), newest first."""
    if MOCK:
        return clean([i for i in mocks.incidents() if int(i["priority"][0]) <= max(max_priority, 4)][:limit])
    rows = _table("incident", f"active=true^priority<={max_priority}^ORDERBYDESCopened_at",
                  "number,short_description,priority,state,cmdb_ci,assignment_group,opened_at", limit)
    for r in rows:
        r["service"] = _service_for_ci(r.get("cmdb_ci", ""))
    return clean(rows)


@mcp.tool()
def list_changes(service: str, hours: int = 24) -> list[dict]:
    """Change requests on the service's CI updated in the last `hours`. Use to correlate
    an incident with a planned change or release."""
    svc = resolve_service(service)
    if MOCK:
        return clean(mocks.changes(svc["name"]))
    q = f"cmdb_ci.name={svc['snow_ci']}^sys_updated_on>=javascript:gs.hoursAgoStart({int(hours)})^ORDERBYDESCstart_date"
    return clean(_table("change_request", q,
                        "number,short_description,state,type,start_date,end_date,cmdb_ci,assignment_group,risk", 20))


@mcp.tool()
def related_incidents(service: str, days: int = 14) -> list[dict]:
    """Recent incidents (open or closed) on the same service. Useful for recurring issues
    and prior fixes (close notes)."""
    svc = resolve_service(service)
    if MOCK:
        return clean(mocks.related_incidents(svc["name"]))
    q = f"cmdb_ci.name={svc['snow_ci']}^opened_at>=javascript:gs.daysAgoStart({int(days)})^ORDERBYDESCopened_at"
    return clean(_table("incident", q, "number,short_description,state,priority,opened_at,close_notes", 15))


@mcp.tool()
def action_add_work_note(number: str, note: str) -> dict:
    """WRITE ACTION. Append a work note to an incident. Only call when a human approved it."""
    if MOCK:
        return {"ok": True, "number": number, "mock": True, "note_chars": len(note)}
    rows = _table("incident", f"number={number.upper()}", "sys_id", 1)
    if not rows:
        return {"ok": False, "error": f"Incident {number} not found"}
    with _client() as c:
        r = c.patch(f"/api/now/table/incident/{rows[0]['sys_id']}", json={"work_notes": note})
        r.raise_for_status()
    return {"ok": True, "number": number}


if __name__ == "__main__":
    run(mcp, 8101)
