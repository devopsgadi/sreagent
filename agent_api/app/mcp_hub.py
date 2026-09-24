"""MCP client side: connect to every configured MCP server for the life of one run,
expose their tools to the LLM with a `<server>__<tool>` name, and route calls back."""
from __future__ import annotations

import json
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

log = logging.getLogger("mcp_hub")
SEP = "__"
ACTION_PREFIX = "action_"  # write tools; never offered to the LLM


@dataclass
class ToolResult:
    server: str
    tool: str
    ok: bool
    text: str
    duration_ms: int


class McpHub:
    def __init__(self, servers: dict[str, str], only: list[str] | None = None):
        self.servers = {k: v for k, v in servers.items() if not only or k in only}
        self.sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, list] = {}
        self.unavailable: dict[str, str] = {}
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "McpHub":
        await self._stack.__aenter__()
        for name, url in self.servers.items():
            try:
                read, write, _ = await self._stack.enter_async_context(streamablehttp_client(url, timeout=15))
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.tools[name] = (await session.list_tools()).tools
                self.sessions[name] = session
            except Exception as e:  # server down or misconfigured: keep going without it
                log.warning("MCP server %s unavailable: %s", name, e)
                self.unavailable[name] = str(e) or e.__class__.__name__
        return self

    async def __aexit__(self, *exc):
        try:
            await self._stack.__aexit__(*exc)
        except Exception as e:  # noqa: BLE001 - transport teardown noise shouldn't fail a run
            log.debug("hub teardown: %s", e)

    def llm_tools(self) -> list[dict]:
        """Read-only tools in OpenAI function format (the LLM adapter converts as needed)."""
        out = []
        for server, tools in self.tools.items():
            for t in tools:
                if t.name.startswith(ACTION_PREFIX):
                    continue
                out.append({"type": "function", "function": {
                    "name": f"{server}{SEP}{t.name}",
                    "description": (t.description or "").strip()[:1000],
                    "parameters": t.inputSchema or {"type": "object", "properties": {}}}})
        return out

    async def call(self, qualified: str, args: dict, allow_actions: bool = False) -> ToolResult:
        server, _, tool = qualified.partition(SEP)
        t0 = time.monotonic()
        if server not in self.sessions:
            return ToolResult(server, tool, False, f"MCP server '{server}' is not available", 0)
        if tool.startswith(ACTION_PREFIX) and not allow_actions:
            return ToolResult(server, tool, False, "Write actions are not allowed from the agent loop", 0)
        try:
            res = await self.sessions[server].call_tool(tool, args or {})
            parts = []
            if getattr(res, "structuredContent", None):
                sc = res.structuredContent
                parts.append(json.dumps(sc.get("result", sc) if isinstance(sc, dict) else sc, default=str))
            else:
                parts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
            return ToolResult(server, tool, not res.isError, "\n".join(parts) or "(empty result)",
                              int((time.monotonic() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ToolResult(server, tool, False, f"{e.__class__.__name__}: {e}", int((time.monotonic() - t0) * 1000))
