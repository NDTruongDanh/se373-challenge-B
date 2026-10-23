"""B2 demo: Code Mode answers over 3 log files without raw logs in context.

Proves (slides 32-33):
  1. the agent answers a multi-file question (FAILED tests, ERROR counts,
     HINT/NOTE/PLAN) via run_code,
  2. raw logs never enter the LLM context (only the aggregated `result` does),
  3. scanned >> returned, measured via usage + tiktoken estimates.

Usage:
  uv run python demo.py --no-agent   # deterministic, no key: canonical program
  uv run python demo.py              # live: LLM writes the program (needs key)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from langchain_core.messages import HumanMessage  # noqa: E402

from src.runner import RUN_STATS, execute_code  # noqa: E402
from src.task import CANONICAL_CODE, TASK, check_answers, estimate_tokens  # noqa: E402

CONTEXT_LINE_CAP = 50  # LLM context must contain no raw (>50-line) message


def report_context(messages: list, returned_chars: int, scanned_chars: int, label: str) -> bool:
    print(f"--- {label}: LLM context ({len(messages)} msgs) ---")
    total = 0
    leak = False
    for m in messages:
        c = m.content if isinstance(m.content, str) else str(m.content)
        nlines = c.count("\n") + 1 if c else 0
        toks = estimate_tokens(c)
        total += toks
        role = type(m).__name__.replace("Message", "")
        preview = (c[:120] + "...") if len(c) > 120 else c
        print(f"[{role} {nlines} lines ~{toks} tok] {preview.splitlines()[0] if preview else ''}")
        if nlines > CONTEXT_LINE_CAP:
            leak = True
    print(f"context total ~{total} est. tokens | scanned inside runtime: {scanned_chars} chars | returned: {returned_chars} chars")
    print(f"raw log kept out of context: {'PASS' if not leak else 'FAIL'}")
    return not leak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-agent", action="store_true", help="offline: run canonical program, no network")
    ap.add_argument("--steps", type=int, default=6)
    args = ap.parse_args()

    from src.config import load_settings

    s = load_settings()
    print(f"settings: base_url={s.base_url} model={s.agent_model} has_key={s.has_key} session={s.session_source}")

    if args.no_agent:
        from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

        from src.agent_graph import SYSTEM_PROMPT

        out, stats = execute_code(CANONICAL_CODE)
        print("--- code-mode result ---")
        print(out)
        print("----------------------")
        messages: list = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=TASK),
            AIMessage(content="I'll aggregate the logs inside run_code.", tool_calls=[{"name": "run_code", "args": {"code": "..."}, "id": "call_demo", "type": "tool_call"}]),
            ToolMessage(content=out, tool_call_id="call_demo"),
            AIMessage(content=out.split("\n", 1)[-1][:1500]),
        ]
        ok_leak = report_context(messages, stats["returned_chars"], stats["scanned_chars"], "deterministic context")
        res = check_answers(out)
        for k, v in res.items():
            print(f"answer {k}: {'PASS' if v else 'FAIL'}")
        ok = all(res.values()) and ok_leak and stats["scanned_chars"] > 100_000 and stats["returned_chars"] <= 2000
        print("B2 RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1

    # Live: the LLM writes the program itself.
    if not s.has_key:
        raise SystemExit("ERROR: no API key (.env at repo root), or rerun with --no-agent.")
    from src.agent_graph import run_task

    state = run_task(TASK, max_steps=args.steps)
    messages = state["messages"]
    usage_in, usage_out = state.get("input_tokens", 0), state.get("output_tokens", 0)
    print(f"live run: {len(messages)} msgs, usage input={usage_in} output={usage_out} run_code calls={RUN_STATS['runs']}")
    # Text blocks only: skip encrypted reasoning blocks (same rule as B1).
    final = state["messages"][-1]
    c = final.content
    if isinstance(c, list):
        final_text = "\n".join(
            b.get("text", "") for b in c
            if isinstance(b, dict) and b.get("type") == "text" and "text" in b
        )
    else:
        final_text = c if isinstance(c, str) else str(c)
    print("--- agent final answer ---")
    print(final_text)
    print("--------------------------")
    res = check_answers(final_text)
    for k, v in res.items():
        print(f"answer {k}: {'PASS' if v else 'FAIL'}")
    scanned = RUN_STATS["total_scanned_chars"]
    ok_leak = report_context(messages, RUN_STATS["last_returned_chars"], scanned, "live context")
    # The agent must have used Code Mode (not hallucinated): at least one run_code call.
    used_codemode = RUN_STATS["runs"] > 0
    print(f"used run_code: {'PASS' if used_codemode else 'FAIL'}")
    ok = all(res.values()) and ok_leak and used_codemode
    print("B2 RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
