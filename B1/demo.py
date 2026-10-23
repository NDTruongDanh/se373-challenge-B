"""B1 demo: long session -> compact -> quiz (slides 32-33).

Proves:
  1. session gets long with large raw logs (tool-output bloat)
  2. compaction shrinks context (input tokens via usage + estimates)
  3. agent still answers: error under investigation? tried? next step?

Usage:
  uv run python demo.py            # full harness: live agent + LLM compact + LLM quiz.
                                   # Any LLM failure raises loudly (no silent fallbacks).
  uv run python demo.py --no-agent # fully deterministic, no network: heuristic checkpoint,
                                   # quiz checks the checkpoint text directly.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from langchain_core.messages import HumanMessage, ToolMessage  # noqa: E402

from src.agent_graph import run_task  # noqa: E402
from src.compaction import EXPECTED, checkpoint_to_markdown, compact_messages, total_input_tokens  # noqa: E402
from src.config import ROOT, load_settings  # noqa: E402
from src.tools import RAW_CHAR_COUNTER, grep_logs, read_log, run_tests_sim  # noqa: E402

TASK = (
    "Investigate the refresh-token race condition. "
    "Constraint: keep API backward compatible (login/refresh signatures unchanged). "
    "Read logs/app.log, logs/test_run.log, run the simulated tests, grep for the race, "
    "then report: failing tests, what was already tried, and the next step."
)

QUIZ = (
    "After compaction, answer in 6 lines max: "
    "1) what error is under investigation? "
    "2) what approaches were already tried? "
    "3) what is the next step? "
    "Do NOT re-read raw logs; use the checkpoint."
)


def deterministic_bloat() -> list:
    """Build a long session without any LLM call (for --no-agent / CI)."""
    msgs: list = [HumanMessage(content=TASK)]
    for fn, kwargs in [
        (read_log, {"name": "app.log", "max_lines": 2000}),
        (run_tests_sim, {}),
        (grep_logs, {"pattern": "race", "name": "grep_noise.log", "max_matches": 1500}),
        (read_log, {"name": "test_run.log", "max_lines": 2000}),
    ]:
        raw = fn.invoke(kwargs) if hasattr(fn, "invoke") else fn(**kwargs)
        text = raw if isinstance(raw, str) else str(raw)
        msgs.append(HumanMessage(content=f"tool:{fn.name if hasattr(fn, 'name') else fn} -> inspect output below"))
        msgs.append(ToolMessage(content=text, tool_call_id=f"call_{len(msgs)}"))
    return msgs


def check_answers(text: str) -> dict[str, bool]:
    low = text.lower()
    return {
        "error": any(k.lower() in low for k in EXPECTED["error"]),
        "tried": any(k.lower() in low for k in EXPECTED["tried"]),
        "next": any(k.lower() in low for k in EXPECTED["next"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-agent", action="store_true", help="skip LLM agent, use deterministic bloat")
    ap.add_argument("--rounds", type=int, default=4)
    args = ap.parse_args()

    s = load_settings()
    print(f"settings: base_url={s.base_url} agent={s.agent_model} compact={s.compact_model} budget={s.token_budget} has_key={s.has_key} session={s.session_source}")

    if args.no_agent:
        # Fully deterministic: no network calls at all.
        messages = deterministic_bloat()
        state = {"messages": messages, "checkpoint_md": "", "compactions": 0, "input_tokens": 0, "output_tokens": 0}
        before = total_input_tokens(messages)
        print(f"long session built: {len(messages)} msgs, ~{before} est. tokens, raw_tool_chars={RAW_CHAR_COUNTER['total']}")
        compact_llm = None
        strict = False
        new_msgs = None  # filled by the forced compaction below
    else:
        if not s.has_key:
            raise SystemExit("ERROR: no API key. Set OPENCODE_API_KEY in .env, or run with --no-agent for deterministic mode.")
        state = run_task(TASK, rounds=args.rounds)
        messages = state["messages"]
        before = total_input_tokens(messages)
        print(f"agent session: {len(messages)} msgs, ~{before} est. tokens, usage input={state.get('input_tokens')} output={state.get('output_tokens')}")
        from src.agent_graph import make_llm

        compact_llm = make_llm(s.compact_model)
        strict = True
        if state.get("compactions", 0) > 0 and state.get("checkpoint_md"):
            # Already compacted in-graph — reuse it instead of re-compacting
            # (a second LLM rewrite can be longer than the checkpoint).
            lc = state.get("last_compact", {})
            md = state["checkpoint_md"]
            stats = {
                "before_tokens": lc.get("before_tokens", before),
                "after_tokens": before,
                "reduction_pct": round(100 * (1 - before / max(1, lc.get("before_tokens", before))), 1),
                "via": lc.get("via", "llm"),
            }
            new_msgs, cp = messages, None
            print(f"[reuse in-graph compact via={stats['via']}] {stats['before_tokens']} -> {stats['after_tokens']} tokens (-{stats['reduction_pct']}%)")
            (ROOT / "checkpoint.md").write_text(md, encoding="utf-8")
            print(f"wrote checkpoint.md ({len(md)} chars)")
        else:
            new_msgs, cp, stats = None, None, None  # filled below

    # Force at least one compaction for the proof (bypass budget if needed),
    # unless the graph already compacted in-graph (handled above).
    if new_msgs is None:
        new_msgs, cp, stats = compact_messages(messages, llm=compact_llm, archive_path=ROOT / "archive" / "session_full.jsonl", strict=strict)
        md = checkpoint_to_markdown(cp, {"created": "demo", "via": stats["via"], "before_tokens": stats["before_tokens"], "after_tokens": stats["after_tokens"]})
        (ROOT / "checkpoint.md").write_text(md, encoding="utf-8")
        print(f"wrote checkpoint.md ({len(md)} chars)")
    print(f"[compact via={stats['via']}] {stats['before_tokens']} -> {stats['after_tokens']} tokens (-{stats['reduction_pct']}%)")

    # Quiz: a live LLM answer in full mode (raises loudly on failure);
    # in --no-agent mode the checkpoint text itself is checked.
    if compact_llm is not None:
        from langchain_core.messages import SystemMessage

        from src.compaction import message_text as _mt

        ans = compact_llm.invoke([SystemMessage(content=md), HumanMessage(content=QUIZ)])
        answer_text = _mt(ans)
    else:
        answer_text = md
    print("--- post-compact answer ---")
    print(answer_text)
    print("---------------------------")

    results = check_answers(answer_text)
    for k, v in results.items():
        print(f"remembers {k}: {'PASS' if v else 'FAIL'}")
    raw_leak = any(len(m.content.splitlines()) > 50 for m in new_msgs[1:] if isinstance(m, ToolMessage))
    print(f"raw log kept out of context: {'PASS' if not raw_leak else 'FAIL'}")
    ok = all(results.values()) and not raw_leak and stats["after_tokens"] < stats["before_tokens"]
    print("B1 RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
