"""Synthetic buggy app for B1: refresh-token race condition.

Mirrors slide 22 (Structured checkpoint example):
  goal: Fix refresh-token race condition
  files: [auth.py, session.py, test_auth.py]
The bug is intentional: no locking around refresh in session.py.
"""
from __future__ import annotations

import threading
import time
import uuid

# Constraint for the task (must survive compaction): keep API backward compatible.
API_VERSION = "v1"


class SessionStore:
    """Naive in-memory session store with a race on refresh."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()  # NOTE: exists but NOT used in refresh() — the bug.

    def login(self, user_id: str) -> dict:
        token = f"tok_{uuid.uuid4().hex[:8]}"
        refresh = {"token": token, "user": user_id, "uses": 0}
        self._sessions[user_id] = refresh
        return refresh

    def refresh(self, user_id: str) -> dict:
        """BUG: read-modify-write without locking. Concurrent calls issue 2 tokens."""
        current = self._sessions.get(user_id)
        if current is None:
            raise KeyError("no session")
        time.sleep(0.005)  # widens the race window so tests catch it
        new_token = f"tok_{uuid.uuid4().hex[:8]}"
        refreshed = {"token": new_token, "user": user_id, "uses": current["uses"] + 1}
        self._sessions[user_id] = refreshed
        return refreshed

    def get(self, user_id: str) -> dict | None:
        return self._sessions.get(user_id)
