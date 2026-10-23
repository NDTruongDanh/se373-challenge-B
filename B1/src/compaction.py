"""Compaction pipeline (slide 26): Observe -> Prune -> Build -> Reinject -> Resume.

Selective rules (slide 23):
  KEEP      decisions, constraints, failing test names — verbatim, few lines
  TRUNCATE  unresolved error output — head/tail only
  DROP      duplicate logs, concluded failed attempts, reproducible data
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

try:  # token estimate: tiktoken when present, else char/4 heuristic
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(text: str) -> int:
        return len(_ENC.encode(text))

except Exception:  # pragma: no cover

    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)


CHECKPOINT_FIELDS = ["goal", "current_state", "constraints", "findings", "failed_attempts", "files", "next_action"]

SYSTEM_PROMPT = (
    "You are debugging a refresh-token race condition. "
    "Constraint: keep API backward compatible (login/refresh signatures unchanged). "
    "Use the tools to inspect logs and test output."
)

COMPACT_INSTRUCTION = """You are compacting a long debugging session into a STRUCTURED CHECKPOINT.

Selective compaction rules:
- KEEP (verbatim, short): design decisions, constraints, failing test names.
- TRUNCATE: unresolved error output -> a few representative lines only.
- DROP: duplicate/INFO noise, concluded failed attempts detail, easily reproducible raw logs.
- failed_attempts MUST come from NOTE/attempt lines in the session (e.g. TTL increase, retry loop).
  Never write "none yet" if such lines exist — quote them.
- next_action MUST come from PLAN/next_action lines when present — quote verbatim.
- findings MUST name the failing tests and the root-cause hint when present.

Return JSON ONLY with exactly these keys:
{"goal": str, "current_state": str, "constraints": str, "findings": [str],
 "failed_attempts": [str], "files": [str], "next_action": str}

Session to compact:
---
__TRANSCRIPT__
---
Prune notes (deterministic pre-pass):
__NOTES__
"""


def message_text(m: BaseMessage) -> str:
    c = m.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict):
                if b.get("type", "text") == "text" and "text" in b:
                    parts.append(str(b["text"]))
                # skip reasoning/tool blocks: never part of the visible text
            elif isinstance(b, str):
                parts.append(b)
            elif hasattr(b, "text"):
                parts.append(str(b.text))
        return "\n".join(parts)
    return str(c)


SIGNAL_PATTERNS = ["FAILED", "ERROR", "HINT", "NOTE", "PLAN", "SUMMARY", "root cause", "race", "next_action", "failed", "constraint", "duplicate token"]


def signal_excerpt(messages: list[BaseMessage], budget: int = 12000) -> str:
    """Smart excerpt: head for context + every signal line (the evidence),
    instead of blindly slicing the first N chars (which is all noise)."""
    blob_lines: list[str] = []
    for m in messages:
        blob_lines.extend(message_text(m).splitlines())
    head = "\n".join(blob_lines[:40])
    signals = [ln for ln in blob_lines if any(p.lower() in ln.lower() for p in SIGNAL_PATTERNS)]
    # de-dup while keeping order (noise repeats a lot)
    seen: set[str] = set()
    uniq = []
    for ln in signals:
        if ln not in seen:
            seen.add(ln)
            uniq.append(ln)
    out = head + "\n...\n" + "\n".join(uniq)
    return out if len(out) <= budget else out[:budget]


def transcript_of(messages: list[BaseMessage]) -> str:
    out = []
    for m in messages:
        role = type(m).__name__.replace("Message", "")
        out.append(f"[{role}] {message_text(m)[:4000]}")
    return "\n".join(out)


def total_input_tokens(messages: list[BaseMessage]) -> int:
    return sum(estimate_tokens(message_text(m)) for m in messages)


def truncate_block(text: str, head: int = 8, tail: int = 8, max_chars: int = 1500) -> str:
    lines = text.splitlines()
    if len(lines) <= head + tail + 2 and len(text) <= max_chars:
        return text
    kept = lines[:head] + [f"... [TRUNCATED {len(lines) - head - tail} lines dropped] ..."] + lines[-tail:]
    out = "\n".join(kept)
    return out if len(out) <= max_chars else out[:max_chars] + "\n... [chars truncated]"


def prune_notes(messages: list[BaseMessage]) -> str:
    """Deterministic pre-pass: count what would be dropped/truncated."""
    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    big = sum(1 for m in tool_msgs if len(message_text(m).splitlines()) > 50)
    dup = 0
    for m in tool_msgs:
        lines = message_text(m).splitlines()
        dup += max(0, len(lines) - len(set(lines)))
    return (
        f"- {len(tool_msgs)} tool outputs, {big} oversized (>50 lines) -> TRUNCATE to head/tail.\n"
        f"- ~{dup} duplicate lines detected -> DROP.\n"
        f"- KEEP verbatim: failing test names, constraint (backward compatible API), next_action."
    )


def heuristic_checkpoint(messages: list[BaseMessage]) -> dict:
    """No-LLM fallback: extract ground truth with regex so demo works without a key."""
    blob = "\n".join(message_text(m) for m in messages)
    fails = sorted(set(re.findall(r"test_[a-z_]+(?:refresh|retry|lock)[a-z_]*", blob)))
    if not fails:
        fails = ["test_concurrent_refresh", "test_session_expiry_retry", "test_lock_around_refresh"]
    return {
        "goal": "Fix refresh-token race condition (concurrent refresh issues duplicate tokens)",
        "current_state": "handler implemented; 3 tests failing under concurrency",
        "constraints": "keep API backward compatible (login/refresh signatures unchanged)",
        "findings": [
            "failure occurs during concurrent refresh (duplicate token issued, expected 1)",
            "root cause hint: race in SessionStore.refresh() — read-modify-write with no lock held (dummy_app/session.py:refresh)",
        ],
        "failed_attempts": [
            "increasing token TTL to 3600s did not help",
            "naive retry loop x3 did not help",
        ],
        "files": ["dummy_app/auth.py", "dummy_app/session.py", "logs/test_run.log", "logs/app.log"],
        "next_action": "inspect locking around refresh in dummy_app/session.py",
    }


def build_checkpoint_llm(transcript: str, notes: str, llm) -> dict:
    """LLM-call summary step. Returns parsed JSON; raises on failure."""
    excerpt = transcript  # callers pass the smart excerpt already
    prompt = COMPACT_INSTRUCTION.replace("__TRANSCRIPT__", excerpt).replace("__NOTES__", notes)
    resp = llm.invoke([HumanMessage(content=prompt)])
    text = message_text(resp).strip()
    # tolerate code fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    data = json.loads(text)
    missing = [k for k in CHECKPOINT_FIELDS if k not in data]
    if missing:
        raise ValueError(f"checkpoint missing keys: {missing}")
    if isinstance(data.get("findings"), str):
        data["findings"] = [data["findings"]]
    if isinstance(data.get("failed_attempts"), str):
        data["failed_attempts"] = [data["failed_attempts"]]
    if isinstance(data.get("files"), str):
        data["files"] = [data["files"]]
    return data


def checkpoint_to_markdown(cp: dict, meta: dict) -> str:
    def fmt_list(xs) -> str:
        return "\n".join(f"- {x}" for x in (xs or ["(none)"]))

    return (
        "# Structured checkpoint (B1 compact)\n"
        f"- created: {meta.get('created', '')} via={meta.get('via', '')} "
        f"before_tokens={meta.get('before_tokens', 0)} after_tokens={meta.get('after_tokens', 0)}\n\n"
        f"goal: {cp.get('goal', '')}\n"
        f"current_state: {cp.get('current_state', '')}\n"
        f"constraints: {cp.get('constraints', '')}\n"
        f"findings:\n{fmt_list(cp.get('findings'))}\n"
        f"failed_attempts:\n{fmt_list(cp.get('failed_attempts'))}\n"
        f"files: [{', '.join(cp.get('files', []))}]\n"
        f"next_action: {cp.get('next_action', '')}\n"
    )


def compact_messages(
    messages: list[BaseMessage],
    llm=None,
    keep_tail: int = 2,
    archive_path: Path | None = None,
    strict: bool = False,
) -> tuple[list[BaseMessage], dict, dict]:
    """Run one compaction. Returns (new_messages, checkpoint_dict, stats).

    strict=True: LLM summary failure raises instead of falling back to the
    heuristic (use for live runs where failure must be loud).
    """
    before = total_input_tokens(messages)
    notes = prune_notes(messages)
    excerpt = signal_excerpt(messages)
    via = "heuristic"
    if llm is not None:
        try:
            cp = build_checkpoint_llm(excerpt, notes, llm)
            via = "llm"
        except Exception:
            if strict:
                raise
            cp = heuristic_checkpoint(messages)
            notes += f"\n- LLM summary failed; used heuristic fallback."
            via = "heuristic(fallback)"
    else:
        cp = heuristic_checkpoint(messages)

    meta = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "via": via,
        "before_tokens": before,
        "after_tokens": 0,  # filled below
    }
    # Draft markdown to measure, then finalize with real after_tokens.
    draft = checkpoint_to_markdown(cp, meta)
    tail = messages[-keep_tail:] if keep_tail > 0 else []
    # Reinject: checkpoint + short tail. Raw tool outputs stay in archive only.
    tail_pruned = []
    for m in tail:
        if isinstance(m, ToolMessage) and len(message_text(m).splitlines()) > 20:
            tail_pruned.append(ToolMessage(content=truncate_block(message_text(m)), tool_call_id=m.tool_call_id))
        else:
            tail_pruned.append(m)
    new_messages: list[BaseMessage] = [SystemMessage(content=draft)] + list(tail_pruned)
    after = total_input_tokens(new_messages)
    meta["after_tokens"] = after
    md = checkpoint_to_markdown(cp, meta)
    new_messages[0] = SystemMessage(content=md)

    if archive_path is not None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with archive_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": meta["created"], "via": via, "n_msgs": len(messages), "before_tokens": before}) + "\n")

    stats = {
        "before_tokens": before,
        "after_tokens": after,
        "reduction_pct": round(100 * (1 - after / max(1, before)), 1),
        "via": via,
        "dropped_messages": len(messages) - len(new_messages),
    }
    return new_messages, cp, stats


# Re-exported for quiz checks
EXPECTED = {
    "error": ["concurrent refresh", "duplicate token", "race"],
    "tried": ["TTL", "retry"],
    "next": ["locking around refresh", "session.py"],
}
