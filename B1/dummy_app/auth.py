"""Auth handler built on SessionStore (backward-compatible API: login/refresh)."""
from __future__ import annotations

from .session import SessionStore

store = SessionStore()


def login(user_id: str) -> dict:
    return store.login(user_id)


def refresh_token(user_id: str) -> dict:
    # Suspected race site: concurrent refresh issues duplicate tokens.
    return store.refresh(user_id)
