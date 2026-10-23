"""Code Mode runtime (slides 28-31): the ONE tool the LLM ever calls.

Write (LLM returns run_code + program) -> Run (runtime executes the program,
the program calls the SDK) -> Receive (LLM gets only the aggregated result).

Runs in-process via exec() in a restricted namespace — a demo-grade sandbox,
NOT a security sandbox (slide 31): no imports, logs/-only file access via
the SDK, wall-clock timeout, output cap. Production would add a real sandbox,
permission checks, timeouts and resource limits.
"""
from __future__ import annotations

import concurrent.futures
import re
import types

from langchain_core.tools import tool

from . import code_tools as ct

MAX_CODE_CHARS = 4000
MAX_RETURN_CHARS = 2000
MAX_RETURN_LINES = 50
TIMEOUT_S = 5.0

# Cumulative stats for the demo's scanned-vs-returned proof.
RUN_STATS = {"runs": 0, "total_scanned_chars": 0, "total_scanned_lines": 0, "last_returned_chars": 0}

DENY_SUBSTRINGS = [
    "__", "import", "open(", "eval(", "exec(", "compile(",
    "getattr", "setattr", "globals", "locals", "vars(", "dir(",
]

SAFE_BUILTINS = {
    "len": len, "range": range, "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "dict": dict, "set": set, "tuple": tuple,
    "sorted": sorted, "min": min, "max": max, "sum": sum,
    "any": any, "all": all, "enumerate": enumerate, "zip": zip,
    "abs": abs, "round": round, "isinstance": isinstance, "print": print,
}

SDK_DOC = """SDK available INSIDE run_code as `tools` (plus `re` module):
- tools.list_logs() -> [names]
- tools.read_lines(name, offset=0, limit=500) -> [lines] (limit max 8000)
- tools.grep_count(name, pattern) -> int (case-insensitive, scans whole file)
- tools.grep_matches(name, pattern, limit=10) -> [lines] (limit max 20)
Allowed files: app.log, test_run.log, grep_noise.log.
Rules: NO imports, NO open(), NO dunders. Aggregate with loops/counters and
assign the final small answer to variable `result` (must be <= 2000 chars,
<= 50 lines). Raw file content never leaves the runtime — only `result` is
returned to you."""


def _build_namespace() -> dict:
    from collections import Counter

    sdk = types.SimpleNamespace(
        list_logs=ct.list_logs,
        read_lines=ct.read_lines,
        grep_count=ct.grep_count,
        grep_matches=ct.grep_matches,
    )
    return {"__builtins__": SAFE_BUILTINS, "tools": sdk, "re": re, "Counter": Counter}


def execute_code(code: str, timeout_s: float = TIMEOUT_S) -> tuple[str, dict]:
    """Run `code` in the restricted runtime. Returns (formatted_output, stats).

    Raises ValueError/TimeoutError with a retryable message on violation.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("ERROR: code must be a non-empty string. Write a program, not a question.")
    if len(code) > MAX_CODE_CHARS:
        raise ValueError(f"ERROR: code too long ({len(code)} > {MAX_CODE_CHARS} chars). Aggregate, don't dump.")
    low = code.lower()
    for bad in DENY_SUBSTRINGS:
        if bad in low:
            raise ValueError(f"ERROR: blocked substring {bad!r} (no imports/file-access/dunders — use the `tools` SDK).")

    def _run():
        ct.reset_stats()
        ns = _build_namespace()
        exec(compile(code, "<code-mode>", "exec"), ns)  # noqa: S102 (demo sandbox, restricted ns)
        if "result" not in ns:
            raise ValueError("ERROR: code must assign variable `result` (e.g. result = {...}). Nothing to return.")
        result_str = str(ns["result"])
        if len(result_str) > MAX_RETURN_CHARS:
            raise ValueError(
                f"ERROR: `result` too large ({len(result_str)} > {MAX_RETURN_CHARS} chars). "
                "Aggregate inside the runtime (counts, top-N, short excerpts) and return only findings."
            )
        if result_str.count("\n") + 1 > MAX_RETURN_LINES:
            raise ValueError(
                f"ERROR: `result` too many lines (> {MAX_RETURN_LINES}). Return a compact summary, not raw lines."
            )
        scanned = dict(ct.RAW_STATS)
        return result_str, scanned

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_run)
        try:
            result_str, scanned = fut.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"ERROR: code timed out after {timeout_s}s. Scan with grep_count, don't loop forever.")

    RUN_STATS["runs"] += 1
    RUN_STATS["total_scanned_chars"] += scanned["chars"]
    RUN_STATS["total_scanned_lines"] += scanned["lines"]
    RUN_STATS["last_returned_chars"] = len(result_str)
    header = (
        f"[code-mode runtime: scanned {scanned['lines']} lines / {scanned['chars']} chars "
        f"in {scanned['calls']} sdk calls; returned {len(result_str)} chars]"
    )
    return header + "\n" + result_str, {
        "scanned_chars": scanned["chars"],
        "scanned_lines": scanned["lines"],
        "sdk_calls": scanned["calls"],
        "returned_chars": len(result_str),
    }


@tool
def run_code(code: str) -> str:
    """Execute a Python program that aggregates over logs/ and returns ONLY findings.

    The program runs in a restricted runtime with a `tools` SDK (list_logs,
    read_lines, grep_count, grep_matches over app.log/test_run.log/grep_noise.log)
    plus `re`/`Counter`. No imports, no open(), no dunders. The program MUST
    assign its small aggregated answer to variable `result` (<=2000 chars,
    <=50 lines). You receive only `result` — raw logs stay inside the runtime.
    """
    try:
        out, _ = execute_code(code)
        return out
    except (ValueError, TimeoutError, MemoryError, OSError) as e:
        return str(e)
    except Exception as e:  # never leak tracebacks as bloat; keep the message short
        return f"ERROR: code raised {type(e).__name__}: {e}. Fix and retry with a smaller aggregation."


TOOLS = [run_code]
