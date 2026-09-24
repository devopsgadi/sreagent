"""Shared helpers for every MCP server: config, service map, HTTP, redaction, trimming."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
from functools import lru_cache
from typing import Any

import httpx
import yaml

MOCK = os.getenv("MOCK", "false").lower() in ("1", "true", "yes")
MAX_ITEMS = int(os.getenv("MCP_MAX_ITEMS", "50"))
MAX_STR = int(os.getenv("MCP_MAX_STR", "800"))


# ---------- time ----------
def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- service map ----------
@lru_cache
def service_map() -> dict[str, dict]:
    default = pathlib.Path(__file__).resolve().parents[2] / "config" / "services.yaml"
    path = os.getenv("SERVICE_MAP_PATH") or str(default)
    with open(path) as f:
        return (yaml.safe_load(f) or {}).get("services", {}) or {}


def resolve_service(name: str) -> dict:
    """Accept a service key, CI name, Datadog service or display name."""
    svcs = service_map()
    if name in svcs:
        return {"name": name, **svcs[name]}
    low = name.lower()
    for key, cfg in svcs.items():
        aliases = {cfg.get("snow_ci"), cfg.get("datadog_service"), cfg.get("display_name")}
        if low in {str(a).lower() for a in aliases if a}:
            return {"name": key, **cfg}
    raise ValueError(f"Unknown service '{name}'. Known services: {', '.join(sorted(svcs))}")


# ---------- HTTP ----------
def http_client(base_url: str, headers: dict | None = None, auth: Any = None) -> httpx.Client:
    verify: Any = os.getenv("CA_BUNDLE") or True
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers=headers or {},
        auth=auth,
        timeout=float(os.getenv("MCP_HTTP_TIMEOUT", "20")),
        verify=verify,
    )


# ---------- redaction ----------
def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


_PAN = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
_RULES = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"(?i)((?:password|passwd|secret|api[_-]?key|token|authorization)\"?\s*[=:]\s*\"?)[^\s\",]+"), r"\1[REDACTED]"),
]


def redact(text: str) -> str:
    def pan(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return "[REDACTED_PAN]" if 13 <= len(digits) <= 19 and _luhn_ok(digits) else m.group(0)

    text = _PAN.sub(pan, text)
    for rx, repl in _RULES:
        text = rx.sub(repl, text)
    return text


def clean(obj: Any, max_items: int = MAX_ITEMS, max_str: int = MAX_STR) -> Any:
    """Redact PII/secrets and cap size so tool results never blow the LLM context."""
    if isinstance(obj, str):
        s = redact(obj)
        return s if len(s) <= max_str else s[:max_str] + f"… [+{len(s) - max_str} chars]"
    if isinstance(obj, dict):
        return {k: clean(v, max_items, max_str) for k, v in obj.items()}
    if isinstance(obj, list):
        out = [clean(v, max_items, max_str) for v in obj[:max_items]]
        if len(obj) > max_items:
            out.append(f"… [{len(obj) - max_items} more items truncated]")
        return out
    return obj


# ---------- entrypoint ----------
def run(mcp, default_port: int) -> None:
    """Run as stdio (VS Code local) or streamable HTTP (docker / agent-api)."""
    p = argparse.ArgumentParser()
    p.add_argument("--transport", choices=["stdio", "http"], default=os.getenv("MCP_TRANSPORT", "http"))
    p.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", default_port)))
    a = p.parse_args()
    if a.transport == "stdio":
        mcp.run()
    else:
        mcp.settings.host = a.host
        mcp.settings.port = a.port
        mcp.run(transport="streamable-http")
