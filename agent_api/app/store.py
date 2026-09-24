"""SQLite persistence (runs, events, audit) + in-process pub/sub for live SSE.
Swap for Postgres/Redis when running more than one agent-api replica."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, incident TEXT, status TEXT, triggered_by TEXT,
  created_at REAL, finished_at REAL, rca TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS runs_incident ON runs(incident, created_at);
CREATE TABLE IF NOT EXISTS events(run_id TEXT, seq INTEGER, ts REAL, type TEXT, data TEXT, PRIMARY KEY(run_id, seq));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, run_id TEXT, actor TEXT,
  action TEXT, params TEXT, result TEXT);
"""
TERMINAL = {"run_finished", "run_failed"}


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._seq: dict[str, int] = {}
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def _x(self, sql: str, args=()):
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur.fetchall()

    # ---- runs ----
    def create_run(self, incident: str, triggered_by: str) -> str:
        rid = uuid.uuid4().hex[:12]
        self._x("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)", (rid, incident, "running", triggered_by, time.time(), None, None, None))
        self._seq[rid] = 0
        return rid

    def finish_run(self, rid: str, status: str, rca: dict | None = None, error: str | None = None):
        self._x("UPDATE runs SET status=?, finished_at=?, rca=?, error=? WHERE id=?",
                (status, time.time(), json.dumps(rca) if rca else None, error, rid))

    def get_run(self, rid: str) -> dict | None:
        rows = self._x("SELECT * FROM runs WHERE id=?", (rid,))
        return self._row(rows[0]) if rows else None

    def list_runs(self, incident: str | None = None, limit: int = 50) -> list[dict]:
        if incident:
            rows = self._x("SELECT * FROM runs WHERE incident=? ORDER BY created_at DESC LIMIT ?", (incident, limit))
        else:
            rows = self._x("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    def latest_by_incident(self) -> dict[str, dict]:
        rows = self._x("SELECT r.* FROM runs r JOIN (SELECT incident, MAX(created_at) m FROM runs GROUP BY incident) x "
                       "ON r.incident=x.incident AND r.created_at=x.m")
        return {r["incident"]: self._row(r) for r in rows}

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["rca"] = json.loads(d["rca"]) if d.get("rca") else None
        return d

    # ---- events ----
    async def emit(self, rid: str, type_: str, data: dict | None = None) -> dict:
        if rid not in self._seq:  # e.g. after a restart
            row = await asyncio.to_thread(self._x, "SELECT COALESCE(MAX(seq), 0) m FROM events WHERE run_id=?", (rid,))
            self._seq[rid] = row[0]["m"]
        self._seq[rid] += 1
        ev = {"run_id": rid, "seq": self._seq[rid], "ts": time.time(), "type": type_, "data": data or {}}
        await asyncio.to_thread(self._x, "INSERT INTO events VALUES(?,?,?,?,?)",
                                (rid, ev["seq"], ev["ts"], type_, json.dumps(ev["data"], default=str)))
        for q in list(self._subs.get(rid, ())):
            q.put_nowait(ev)
        return ev

    def events(self, rid: str, after: int = 0) -> list[dict]:
        rows = self._x("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (rid, after))
        return [{"run_id": r["run_id"], "seq": r["seq"], "ts": r["ts"], "type": r["type"], "data": json.loads(r["data"])} for r in rows]

    def subscribe(self, rid: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(rid, set()).add(q)
        return q

    def unsubscribe(self, rid: str, q: asyncio.Queue):
        self._subs.get(rid, set()).discard(q)

    # ---- audit ----
    def audit(self, rid: str, actor: str, action: str, params: dict, result: dict):
        self._x("INSERT INTO audit(ts, run_id, actor, action, params, result) VALUES(?,?,?,?,?,?)",
                (time.time(), rid, actor, action, json.dumps(params), json.dumps(result)))

    def audit_log(self, rid: str | None = None) -> list[dict]:
        rows = self._x("SELECT * FROM audit WHERE run_id=? ORDER BY ts DESC", (rid,)) if rid else \
            self._x("SELECT * FROM audit ORDER BY ts DESC LIMIT 200")
        return [dict(r) for r in rows]


store = Store(settings.db_path)
