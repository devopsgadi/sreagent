from __future__ import annotations

import os


def _b(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


class Settings:
    llm_provider = os.getenv("LLM_PROVIDER", "mock")
    llm_base_url = (os.getenv("LLM_BASE_URL") or "").rstrip("/")
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "")
    azure_api_version = os.getenv("AZURE_API_VERSION", "2024-10-21")
    llm_timeout = float(os.getenv("LLM_TIMEOUT", "90"))
    llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2000"))
    ca_bundle = os.getenv("CA_BUNDLE") or None
    # Demo pacing for LLM_PROVIDER=mock so the live UI is watchable.
    mock_step_delay = float(os.getenv("MOCK_STEP_DELAY", "1.2"))

    # name -> streamable HTTP URL. Order is the display order in the UI.
    mcp_servers = {
        "servicenow": os.getenv("SERVICENOW_MCP_URL", "http://localhost:8101/mcp"),
        "datadog": os.getenv("DATADOG_MCP_URL", "http://localhost:8102/mcp"),
        "kibana": os.getenv("KIBANA_MCP_URL", "http://localhost:8103/mcp"),
        "gitlab": os.getenv("GITLAB_MCP_URL", "http://localhost:8104/mcp"),
    }

    max_steps = int(os.getenv("AGENT_MAX_STEPS", "10"))
    tool_result_max_chars = int(os.getenv("TOOL_RESULT_MAX_CHARS", "6000"))
    db_path = os.getenv("DB_PATH", "./sre_agent.db")

    enable_actions = _b("ENABLE_ACTIONS")
    require_user_header = _b("REQUIRE_USER_HEADER")
    webhook_secret = os.getenv("WEBHOOK_SECRET", "")
    auto_triage_priorities = {p.strip() for p in os.getenv("AUTO_TRIAGE_PRIORITIES", "1,2").split(",") if p.strip()}
    cors_origins = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o]


settings = Settings()
