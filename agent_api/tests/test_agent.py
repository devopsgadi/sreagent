import json
import os
import sys
import pathlib

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("MOCK_STEP_DELAY", "0")
os.environ.setdefault("DB_PATH", ":memory:")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "mcp_servers"))

from app import llm  # noqa: E402
from app.agent import _parse_rca  # noqa: E402
from sre_mcp.common import clean, redact, resolve_service  # noqa: E402


def test_parse_rca_strips_fences_and_fills_defaults():
    rca = _parse_rca('```json\n{"summary": "x", "confidence": "high"}\n```')
    assert rca["summary"] == "x" and rca["timeline"] == [] and rca["recommended_actions"] == []


def test_parse_rca_rejects_prose():
    with pytest.raises(ValueError):
        _parse_rca("I think it was the deploy.")


def test_redaction():
    out = redact("card 4111 1111 1111 1111 mail a.b@x.com Bearer abc.def ssn 123-45-6789 id 1234567890123")
    assert "4111" not in out and "a.b@x.com" not in out and "abc.def" not in out and "123-45-6789" not in out
    assert "1234567890123" in out  # not Luhn-valid, left alone


def test_clean_truncates():
    out = clean({"s": "x" * 5000, "l": list(range(200))}, max_items=10, max_str=100)
    assert len(out["s"]) < 200 and len(out["l"]) == 11


def test_service_aliases():
    assert resolve_service("Payments API")["name"] == "payments-api"
    with pytest.raises(ValueError):
        resolve_service("nope")


TOOLS = [{"type": "function", "function": {"name": n, "description": "", "parameters": {}}} for n in [
    "servicenow__get_incident", "servicenow__list_changes", "datadog__get_active_monitors", "datadog__query_metric",
    "kibana__error_histogram", "kibana__top_error_signatures", "gitlab__list_deployments",
    "gitlab__get_merge_request_changes"]]


@pytest.mark.asyncio
async def test_mock_llm_plays_playbook_then_answers():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "Triage incident INC0048213."}]
    first = await llm.chat(msgs, TOOLS)
    assert first.tool_calls[0].name == "servicenow__get_incident"
    assert first.tool_calls[0].arguments == {"number": "INC0048213"}
    # feed empty results through remaining steps until it answers
    for _ in range(8):
        resp = await llm.chat(msgs, TOOLS)
        if not resp.tool_calls:
            break
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": t.id, "type": "function", "function": {"name": t.name, "arguments": json.dumps(t.arguments)}}
            for t in resp.tool_calls]})
        msgs += [{"role": "tool", "tool_call_id": t.id, "content": "[]"} for t in resp.tool_calls]
    rca = json.loads(resp.content)
    assert rca["confidence"] == "low"
