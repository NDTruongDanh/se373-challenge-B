"""Env + model config. Uses opencode Go API key (OpenAI-compatible)."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# Direct Go inference endpoint (per https://opencode.ai/docs/go/#endpoints).
# The old .../zen/go/v1 multiplex endpoint requires a server-side session and
# is NOT used here. muse-spark lives at .../openai/v1/responses.
DEFAULT_BASE_URL = "https://opencode.ai/inference/go/openai/v1"
USER_AGENT = "se373-b1-compact/0.1.0"


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    agent_model: str
    compact_model: str
    token_budget: int
    has_key: bool
    session_id: str = ""
    session_source: str = ""  # "env" | "generated"


def load_settings() -> Settings:
    api_key = os.getenv("OPENCODE_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or DEFAULT_BASE_URL
    agent_model = os.getenv("AGENT_MODEL", "muse-spark-1.3-contributor").strip()
    compact_model = os.getenv("COMPACT_MODEL", agent_model).strip()
    try:
        budget = int(os.getenv("TOKEN_BUDGET", "8000"))
    except ValueError:
        budget = 8000
    # x-opencode-session is a client-chosen stable id per conversation
    # (https://opencode.ai/docs/go/#where-can-i-use-it), NOT a server session.
    session_id = os.getenv("OPENCODE_SESSION_ID", "").strip()
    source = "env"
    if not session_id:
        session_id = f"b1-{uuid.uuid4().hex[:12]}"
        source = "generated"
    return Settings(
        api_key=api_key,
        base_url=base_url,
        agent_model=agent_model,
        compact_model=compact_model,
        token_budget=budget,
        has_key=bool(api_key),
        session_id=session_id,
        session_source=source,
    )
