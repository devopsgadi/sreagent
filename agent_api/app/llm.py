"""LLM adapter. Internal message format is OpenAI chat style; converted for Anthropic.
Providers: openai (any OpenAI-compatible gateway), azure (Azure OpenAI), anthropic, mock."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

import httpx

from .config import settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.llm_timeout, verify=settings.ca_bundle or True)


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


# ---------------- OpenAI-compatible + Azure ----------------
async def _openai(messages: list[dict], tools: list[dict] | None, azure: bool) -> LLMResponse:
    body: dict = {"messages": messages, "max_tokens": settings.llm_max_tokens, "temperature": 0.1}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if azure:
        url = (f"{settings.llm_base_url}/openai/deployments/{settings.llm_model}/chat/completions"
               f"?api-version={settings.azure_api_version}")
        headers = {"api-key": settings.llm_api_key}
    else:
        url = f"{settings.llm_base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
        body["model"] = settings.llm_model
    async with _client() as c:
        r = await c.post(url, json=body, headers=headers)
        r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    calls = [ToolCall(tc["id"], tc["function"]["name"], _parse_args(tc["function"].get("arguments")))
             for tc in (msg.get("tool_calls") or [])]
    return LLMResponse(msg.get("content"), calls)


# ---------------- Anthropic ----------------
def _to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    system, out = "", []
    for m in messages:
        role = m["role"]
        if role == "system":
            system += m["content"] + "\n"
        elif role == "assistant":
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                               "input": _parse_args(tc["function"]["arguments"])})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "."}]})
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": "user", "content": m["content"]})
    return system.strip(), out


async def _anthropic(messages: list[dict], tools: list[dict] | None) -> LLMResponse:
    system, msgs = _to_anthropic(messages)
    body: dict = {"model": settings.llm_model, "max_tokens": settings.llm_max_tokens, "system": system, "messages": msgs}
    if tools:
        body["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"],
                          "input_schema": t["function"]["parameters"]} for t in tools]
    async with _client() as c:
        r = await c.post(f"{settings.llm_base_url}/v1/messages", json=body, headers={
            "x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01"})
        r.raise_for_status()
    data = r.json()
    text = "".join(b["text"] for b in data["content"] if b["type"] == "text") or None
    calls = [ToolCall(b["id"], b["name"], b["input"]) for b in data["content"] if b["type"] == "tool_use"]
    return LLMResponse(text, calls)


# ---------------- Mock (scripted, uses real MCP tool results) ----------------
def _tool_outputs(messages: list[dict]) -> dict[str, list]:
    """Map tool name -> parsed JSON outputs seen so far."""
    names = {}
    for m in messages:
        for tc in m.get("tool_calls") or []:
            names[tc["id"]] = tc["function"]["name"]
    out: dict[str, list] = {}
    for m in messages:
        if m["role"] == "tool":
            try:
                val = json.loads(m["content"])
            except (json.JSONDecodeError, TypeError):
                val = m["content"]
            out.setdefault(names.get(m["tool_call_id"], "?"), []).append(val)
    return out


def _mock(messages: list[dict], tools: list[dict] | None) -> LLMResponse:
    available = {t["function"]["name"] for t in tools or []}
    user = next(m["content"] for m in messages if m["role"] == "user")
    number = (re.search(r"INC\d+", user) or re.search(r"\w+", user)).group(0)
    seen = _tool_outputs(messages)
    step = sum(1 for m in messages if m["role"] == "assistant" and m.get("tool_calls"))

    inc = (seen.get("servicenow__get_incident") or [{}])[0]
    service = (inc.get("service") if isinstance(inc, dict) else None) or "payments-api"
    deploys = (seen.get("gitlab__list_deployments") or [[]])[0] or []
    mr_iid = None
    if isinstance(deploys, list) and deploys and isinstance(deploys[0], dict) and deploys[0].get("merge_requests"):
        mr_iid = deploys[0]["merge_requests"][0]["iid"]

    plan = [
        [("servicenow__get_incident", {"number": number})],
        [("datadog__get_active_monitors", {"service": service}),
         ("datadog__query_metric", {"service": service, "metric": "error_rate", "minutes": 120})],
        [("kibana__error_histogram", {"service": service, "minutes": 120}),
         ("kibana__top_error_signatures", {"service": service, "minutes": 60})],
        [("gitlab__list_deployments", {"service": service, "hours": 24}),
         ("servicenow__list_changes", {"service": service, "hours": 24})],
        [("gitlab__get_merge_request_changes", {"service": service, "mr_iid": mr_iid})] if mr_iid else [],
    ]
    batches = [[(n, a) for n, a in b if n in available] for b in plan]
    batches = [b for b in batches if b]
    if step < len(batches):
        return LLMResponse(None, [ToolCall(f"call_{step}_{i}", n, a) for i, (n, a) in enumerate(batches[step])])
    return LLMResponse(json.dumps(_mock_rca(number, service, seen)))


def _mock_rca(number: str, service: str, seen: dict) -> dict:
    deploys = (seen.get("gitlab__list_deployments") or [[]])[0] or []
    sigs = ((seen.get("kibana__top_error_signatures") or [{}])[0] or {}).get("signatures", [])
    hist = (seen.get("kibana__error_histogram") or [{}])[0] or {}
    monitors = (seen.get("datadog__get_active_monitors") or [[]])[0] or []
    metric = (seen.get("datadog__query_metric") or [{}])[0] or {}
    mr = (seen.get("gitlab__get_merge_request_changes") or [{}])[0] or {}
    changes = (seen.get("servicenow__list_changes") or [[]])[0] or []
    inc = (seen.get("servicenow__get_incident") or [{}])[0] or {}
    top = next((s for s in sigs if s.get("count")), None)
    deploy = deploys[0] if deploys else None

    timeline, evidence = [], []
    if deploy:
        timeline.append({"time": deploy["created_at"], "source": "gitlab", "event": f"Deploy {deploy['ref']} to production"})
    if hist.get("estimated_onset"):
        timeline.append({"time": hist["estimated_onset"], "source": "kibana", "event": "Error volume jumps above baseline"})
    for m in monitors[:2]:
        timeline.append({"time": m["state_changed_at"], "source": "datadog", "event": f"{m['name']} → {m['overall_state']}"})
    if inc.get("opened_at"):
        timeline.append({"time": inc["opened_at"], "source": "servicenow", "event": f"{number} opened"})
    timeline.sort(key=lambda x: x["time"])

    if metric.get("max") is not None:
        evidence.append({"source": "datadog", "finding": f"error_rate peaked at {metric['max']}{metric.get('unit', '')} vs baseline {metric.get('baseline')}", "ref": "datadog__query_metric"})
    if top:
        evidence.append({"source": "kibana", "finding": f"{top['count']}× {top['error_type']}: {top.get('sample', '')[:140]}", "ref": "kibana__top_error_signatures"})
    if mr.get("files"):
        evidence.append({"source": "gitlab", "finding": f"!{mr['iid']} '{mr['title']}' changed {', '.join(f['path'] for f in mr['files'])}", "ref": mr.get("web_url", "")})
    for ch in changes[:1]:
        evidence.append({"source": "servicenow", "finding": f"{ch['number']} {ch['short_description']} ({ch['state']})", "ref": ch["number"]})

    if deploy and top and mr:
        return {
            "summary": f"{service} errors began minutes after deploy {deploy['ref']}. "
                       f"Dominant error is {top['error_type']}; MR !{mr['iid']} reduced the DB connection pool.",
            "probable_cause": f"MR !{mr['iid']} lowered db.pool.maxSize from 50 to 10 in values-prod.yaml. "
                              "Under production load the pool exhausts and requests time out waiting for ledger-db connections.",
            "confidence": "high", "service": service, "timeline": timeline, "evidence": evidence,
            "recommended_actions": [
                {"type": "rollback", "action": f"Roll back to {deploys[1]['ref'] if len(deploys) > 1 else 'previous release'}",
                 "details": f"Revert !{mr['iid']} or redeploy the previous tag under the existing change.", "mr_iid": mr["iid"], "service": service},
                {"type": "work_note", "action": f"Post RCA draft to {number}", "details": "Keeps the incident record current for the bridge."},
                {"type": "investigate", "action": "Load-test pool sizing before re-release", "details": "Validate maxSize against peak TPS."}],
            "open_questions": ["Was the pool change intended for a lower-traffic environment only?"],
        }
    return {"summary": f"No clear change-related cause found for {service}.",
            "probable_cause": "Insufficient evidence from connected sources.", "confidence": "low", "service": service,
            "timeline": timeline, "evidence": evidence,
            "recommended_actions": [{"type": "investigate", "action": "Check infrastructure and dependencies", "details": "Kubernetes events, Azure health, upstream services."}],
            "open_questions": ["Are there dependency incidents not linked to this CI?"]}


async def chat(messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
    p = settings.llm_provider
    if p == "mock":
        await asyncio.sleep(settings.mock_step_delay)
        return _mock(messages, tools)
    if p in ("openai", "azure"):
        return await _openai(messages, tools, azure=(p == "azure"))
    if p == "anthropic":
        return await _anthropic(messages, tools)
    raise ValueError(f"Unknown LLM_PROVIDER '{p}'")
