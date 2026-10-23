"""B2 verify: offline proof that Code Mode keeps raw logs out of context.

Checks (no API key needed):
  1. canonical program runs in the sandbox and answers all 6 checks
     (3 FAILED tests, app ERROR count, grep count, hint, tried, next)
  2. scanned >> returned (raw stays inside the runtime)
  3. `result` cap enforced (oversized dump rejected)
  4. sandbox blocks: path escape, imports, open(), dunders
  5. estimated LLM context stays small (no raw leak)

Usage: uv run python verify.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.runner import execute_code  # noqa: E402
from src.task import CANONICAL_CODE, check_answers, estimate_tokens  # noqa: E402


def main() -> int:
    failures: list[str] = []

    # 1. canonical program answers correctly
    out, stats = execute_code(CANONICAL_CODE)
    res = check_answers(out)
    for k, v in res.items():
        if not v:
            failures.append(f"canonical answer misses: {k}")
    print(f"canonical: scanned={stats['scanned_chars']} chars/{stats['scanned_lines']} lines in {stats['sdk_calls']} calls -> returned={stats['returned_chars']} chars")

    # 2. scanned >> returned
    if not stats["scanned_chars"] > 100_000:
        failures.append(f"sandbox scanned too little: {stats['scanned_chars']} chars (logs missing?)")
    if not stats["returned_chars"] <= 2000:
        failures.append(f"returned too large: {stats['returned_chars']} chars")
    ratio = stats["scanned_chars"] / max(1, stats["returned_chars"])
    print(f"reduction ratio: {ratio:.0f}x scanned-vs-returned")
    if ratio < 50:
        failures.append(f"reduction ratio too small: {ratio:.1f}x")

    # 3. oversized dump rejected (script must aggregate, slide 33)
    try:
        execute_code("result = '\\n'.join(tools.read_lines('test_run.log', 0, 8000))")
        failures.append("oversized `result` was NOT rejected")
    except ValueError as e:
        print(f"dump cap enforced: {e}")

    # 4. sandbox blocks
    for evil, why in [
        ("result = open('x').read()", "open()"),
        ("import os\nresult = 'x'", "import"),
        ("result = tools.read_lines('../../secret', 0, 5)", "path escape"),
        ("result = (1).__class__", "dunders"),
    ]:
        try:
            execute_code(evil)
            failures.append(f"sandbox did NOT block: {why}")
        except (ValueError, FileNotFoundError) as e:
            print(f"sandbox blocks {why}: {str(e)[:80]}")
        except Exception as e:  # runner wraps runtime errors as ERROR strings, not raises
            print(f"sandbox blocks {why} (runtime error): {str(e)[:80]}")

    # 5. context stays small: task + result only
    from src.task import TASK

    ctx = TASK + "\n" + out
    toks = estimate_tokens(ctx)
    print(f"LLM context estimate: ~{toks} tokens (task + aggregated result only)")
    if toks > 3000:
        failures.append(f"context too large: ~{toks} tokens")

    if failures:
        print("VERIFY FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("VERIFY PASS: multi-file answer correct, raw logs stayed inside the runtime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
