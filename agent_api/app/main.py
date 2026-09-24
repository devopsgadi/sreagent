"""agent-api: REST + SSE for the SRE agent UI."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent import run_triage
from .config import settings
from .mcp_hub import McpHub
from .store import TERMINAL, store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(title="SRE Agent API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
_tasks: set[asyncio.Task] = set()


def actor(x_forwarded_user: str | None, x_user: str | None) -> str:
    user = x_forwarded_user or x_user
    if not user and settings.require_user_header:
        raise HTTPException(401, "Missing identity header (X-Forwarded-User)")
    return user or "anonymous"


def start_run(incident: str, who: str) -> str:
    rid = store.create_run(incident.upper(), who)
    t = asyncio.create_task(run_triage(rid, incident.upper()))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return rid


# ---------------- read ----------------
@app.get("/api/health")
async def health():
    return {"ok": True, "llm": settings.llm_provider, "actions_enabled": settings.enable_actions}


@app.get("/api/sources")
async def sources():
    async with McpHub(settings.mcp_servers) as hub:
        return {name: {"url": url, "ok": name in hub.sessions, "tools": [t.name for t in hub.tools.get(name, [])],
                       "error": hub.unavailable.get(name)} for name, url in settings.mcp_servers.items()}


@app.get("/api/incidents")
async def incidents(max_priority: int = 4):
    rows, error = [], None
    async with McpHub(settings.mcp_servers, only=["servicenow"]) as hub:
        res = await hub.call("servicenow__list_open_incidents", {"max_priority": max_priority}, allow_actions=False)
        if res.ok:
            try:
                rows = json.loads(res.text)
            except json.JSONDecodeError:
                error = "Unexpected response from ServiceNow"
        else:
            error = res.text
    latest = store.latest_by_incident()
    for r in rows:
        run = latest.get(r["number"])
        r["last_run"] = {k: run[k] for k in ("id", "status", "created_at", "finished_at")} | \
            {"confidence": (run.get("rca") or {}).get("confidence")} if run else None
    return {"incidents": rows, "error": error}


@app.get("/api/runs")
async def runs(incident: str | None = None):
    return store.list_runs(incident)


@app.get("/api/runs/{rid}")
async def run(rid: str):
    r = store.get_run(rid)
    if not r:
        raise HTTPException(404, "Run not found")
    return r


@app.get("/api/runs/{rid}/events")
async def run_events(rid: str, request: Request):
    """Server-Sent Events: replays stored events, then streams live ones until the run ends."""
    if not store.get_run(rid):
        raise HTTPException(404, "Run not found")
    last_id = int(request.headers.get("last-event-id") or 0)

    async def gen():
        q = store.subscribe(rid)
        try:
            last = last_id
            for ev in store.events(rid, after=last):
                last = ev["seq"]
                yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
                if ev["type"] in TERMINAL:
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
                if ev["type"] in TERMINAL:
                    return
        finally:
            store.unsubscribe(rid, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- triage ----------------
class TriageIn(BaseModel):
    incident: str = Field(pattern=r"^[A-Za-z]{2,5}\d{4,12}$")


@app.post("/api/triage")
async def triage(body: TriageIn, x_forwarded_user: str | None = Header(None), x_user: str | None = Header(None)):
    return {"run_id": start_run(body.incident, actor(x_forwarded_user, x_user))}


# ---------------- actions (human-approved writes) ----------------
class ActionIn(BaseModel):
    action: str  # post_work_note | draft_rollback_mr
    confirm: bool = False


def _work_note(run: dict) -> str:
    rca = run["rca"]
    lines = [f"[SRE agent RCA draft · confidence {rca.get('confidence')}]", "", rca.get("summary", ""), "",
             "Probable cause: " + rca.get("probable_cause", ""), "", "Evidence:"]
    lines += [f"- ({e.get('source')}) {e.get('finding')}" for e in rca.get("evidence", [])]
    lines += ["", "Recommended:"] + [f"- {a.get('action')}" for a in rca.get("recommended_actions", [])]
    return "\n".join(lines)


@app.post("/api/runs/{rid}/actions")
async def run_action(rid: str, body: ActionIn, x_forwarded_user: str | None = Header(None), x_user: str | None = Header(None)):
    who = actor(x_forwarded_user, x_user)
    if not settings.enable_actions:
        raise HTTPException(403, "Write actions are disabled. Set ENABLE_ACTIONS=true to allow them.")
    if not body.confirm:
        raise HTTPException(400, "Actions need confirm=true")
    run = store.get_run(rid)
    if not run or not run.get("rca"):
        raise HTTPException(404, "Run has no RCA yet")
    rca = run["rca"]
    if body.action == "post_work_note":
        tool, args = "servicenow__action_add_work_note", {"number": run["incident"], "note": _work_note(run)}
    elif body.action == "draft_rollback_mr":
        rb = next((a for a in rca.get("recommended_actions", []) if a.get("type") == "rollback" and a.get("mr_iid")), None)
        if not rb:
            raise HTTPException(400, "RCA has no rollback action tied to a merge request")
        tool, args = "gitlab__action_create_rollback_mr", {
            "service": rb.get("service") or rca.get("service"), "mr_iid": int(rb["mr_iid"]),
            "reason": f"{run['incident']}: {rca.get('probable_cause', '')}"[:500]}
    else:
        raise HTTPException(400, f"Unknown action '{body.action}'")
    server = tool.split("__")[0]
    async with McpHub(settings.mcp_servers, only=[server]) as hub:
        res = await hub.call(tool, args, allow_actions=True)
    try:
        result = json.loads(res.text)
    except json.JSONDecodeError:
        result = {"text": res.text}
    result["ok"] = res.ok and result.get("ok", True)
    store.audit(rid, who, body.action, args, result)
    await store.emit(rid, "action_done", {"action": body.action, "actor": who, "result": result})
    if not result["ok"]:
        raise HTTPException(502, result.get("error") or result.get("text") or "Action failed")
    return result


@app.get("/api/audit")
async def audit(run_id: str | None = None):
    return store.audit_log(run_id)


# ---------------- ServiceNow webhook ----------------
@app.post("/api/webhooks/servicenow")
async def snow_webhook(request: Request, x_webhook_secret: str | None = Header(None)):
    """Configure a ServiceNow Business Rule / Flow to POST {"number": "...", "priority": "2"} on insert."""
    if not settings.webhook_secret or not hmac.compare_digest(x_webhook_secret or "", settings.webhook_secret):
        raise HTTPException(401, "Bad webhook secret")
    body = await request.json()
    number, prio = str(body.get("number", "")), str(body.get("priority", "")).strip()[:1]
    if not number:
        raise HTTPException(400, "number is required")
    if prio not in settings.auto_triage_priorities:
        return {"skipped": True, "reason": f"priority {prio} not in AUTO_TRIAGE_PRIORITIES"}
    return {"run_id": start_run(number, "servicenow-webhook")}
