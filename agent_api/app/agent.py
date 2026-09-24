"""The triage loop. Every step is emitted as an event so the UI can render progress live."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from . import llm
from .config import settings
from .mcp_hub import McpHub
from .prompts import FINALIZE, SYSTEM, user_prompt
from .store import store

log = logging.getLogger("agent")


def _parse_rca(text: str | None) -> dict:
    if not text:
        raise ValueError("LLM returned no content")
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("No JSON object in LLM output")
    rca = json.loads(cleaned[start:end + 1])
    for k, default in (("timeline", []), ("evidence", []), ("recommended_actions", []), ("open_questions", []),
                       ("confidence", "low"), ("summary", ""), ("probable_cause", "")):
        rca.setdefault(k, default)
    return rca


def _preview(text: str, n: int = 240) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[:n] + "…"


async def run_triage(rid: str, incident: str) -> None:
    await store.emit(rid, "run_started", {"incident": incident, "llm": settings.llm_provider})
    try:
        async with McpHub(settings.mcp_servers) as hub:
            await store.emit(rid, "sources", {
                "available": {k: len(v) for k, v in hub.tools.items()},
                "unavailable": hub.unavailable})
            tools = hub.llm_tools()
            if not tools:
                raise RuntimeError("No MCP servers reachable")
            messages: list[dict] = [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": user_prompt(incident)}]
            resp = None
            for step in range(1, settings.max_steps + 1):
                await store.emit(rid, "llm_step", {"step": step})
                resp = await llm.chat(messages, tools)
                if resp.content and resp.tool_calls:
                    await store.emit(rid, "agent_note", {"text": _preview(resp.content, 600)})
                if not resp.tool_calls:
                    break
                messages.append({"role": "assistant", "content": resp.content, "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}} for tc in resp.tool_calls]})
                for tc in resp.tool_calls:
                    server, _, tool = tc.name.partition("__")
                    await store.emit(rid, "tool_started", {"call_id": tc.id, "source": server, "tool": tool, "args": tc.arguments})
                results = await asyncio.gather(*(hub.call(tc.name, tc.arguments) for tc in resp.tool_calls))
                for tc, res in zip(resp.tool_calls, results):
                    await store.emit(rid, "tool_finished", {
                        "call_id": tc.id, "source": res.server, "tool": res.tool, "ok": res.ok,
                        "duration_ms": res.duration_ms, "preview": _preview(res.text),
                        "result": res.text[:settings.tool_result_max_chars]})
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": res.text[:settings.tool_result_max_chars]})
            else:
                messages.append({"role": "user", "content": FINALIZE})
                resp = await llm.chat(messages, None)

            await store.emit(rid, "llm_step", {"step": "summarize"})
            try:
                rca = _parse_rca(resp.content if resp else None)
            except (ValueError, json.JSONDecodeError):
                messages.append({"role": "assistant", "content": resp.content if resp else ""})
                messages.append({"role": "user", "content": "That was not valid JSON. " + FINALIZE})
                rca = _parse_rca((await llm.chat(messages, None)).content)
            await store.emit(rid, "rca_ready", rca)
        store.finish_run(rid, "triaged", rca=rca)
        await store.emit(rid, "run_finished", {"status": "triaged"})
    except Exception as e:  # noqa: BLE001
        log.exception("run %s failed", rid)
        store.finish_run(rid, "failed", error=str(e))
        await store.emit(rid, "run_failed", {"error": f"{e.__class__.__name__}: {e}"})
