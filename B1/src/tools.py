"""Agent tools that deliberately produce tool-output bloat (slide 19).

Raw outputs are large (thousands of lines). The agent only needs a few
findings — everything else is a DROP candidate during compaction.
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT.parent / "logs"  # repo root logs/ (shared with B2)

# Counts raw chars ever returned (to prove raw logs never enter post-compact context).
RAW_CHAR_COUNTER = {"total": 0}


def _bump(raw: str) -> str:
    RAW_CHAR_COUNTER["total"] += len(raw)
    return raw


@tool
def read_log(name: str, max_lines: int = 2000) -> str:
    """Read a synthetic log file. Returns LOTS of lines (bloat on purpose)."""
    path = (LOG_DIR / name).resolve()
    if LOG_DIR not in path.parents:
        return "ERROR: path escape blocked"
    if not path.exists():
        return f"ERROR: {name} not found in logs/. Run: uv run python generate_logs.py"
    lines = path.read_text(encoding="utf-8").splitlines()
    head = lines[:max_lines]
    note = f"[read_log {name}: showing {len(head)}/{len(lines)} lines, {path.stat().st_size} bytes raw]"
    return _bump(note + "\n" + "\n".join(head))


@tool
def grep_logs(pattern: str, name: str = "grep_noise.log", max_matches: int = 1500) -> str:
    """Grep a log for a pattern. Returns up to 1500 matching lines (bloat)."""
    path = (LOG_DIR / name).resolve()
    if LOG_DIR not in path.parents or not path.exists():
        return f"ERROR: {name} not found. Run generate_logs.py first."
    out = [f"[grep '{pattern}' in {name}]"]
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if pattern.lower() in line.lower():
            out.append(line)
            count += 1
            if count >= max_matches:
                break
    out.append(f"[{count} matches]")
    return _bump("\n".join(out))


@tool
def run_tests_sim() -> str:
    """Simulated test run with ~7000 lines of output; 3 FAILs buried inside."""
    path = LOG_DIR / "test_run.log"
    if not path.exists():
        return "ERROR: logs/test_run.log missing. Run generate_logs.py first."
    # Return the whole file: this is the 7k-line bloat the slides describe.
    content = path.read_text(encoding="utf-8")
    return _bump(f"[run_tests_sim: {len(content.splitlines())} lines, {len(content)} bytes raw]\n" + content)


TOOLS = [read_log, grep_logs, run_tests_sim]
