"""B1 verify: automated proof that compaction keeps what matters (slide 32).

Checks:
  1. checkpoint.md has all Structured Checkpoint fields (slide 22)
  2. remembers error / tried / next (ground-truth keywords)
  3. context shrank (after < before, reduction >= 50%)
  4. raw log bloat is out of the active context (no >50-line tool msg post-compact)

Usage: uv run python verify.py  (uses --no-agent path, no API key needed)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from langchain_core.messages import ToolMessage  # noqa: E402

from src.compaction import CHECKPOINT_FIELDS, compact_messages, total_input_tokens  # noqa: E402
from demo import check_answers, deterministic_bloat  # noqa: E402


def main() -> int:
    failures: list[str] = []
    messages = deterministic_bloat()
    before = total_input_tokens(messages)
    new_msgs, cp, stats = compact_messages(messages, llm=None)
    md_path = ROOT / "checkpoint.md"
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

    # 1. schema
    for f in CHECKPOINT_FIELDS:
        if f not in cp:
            failures.append(f"checkpoint missing field: {f}")
    if md and "next_action" not in md:
        failures.append("checkpoint.md missing next_action")

    # 2. memory
    from src.compaction import checkpoint_to_markdown

    text = checkpoint_to_markdown(cp, {"created": "verify", "via": "heuristic", "before_tokens": stats["before_tokens"], "after_tokens": stats["after_tokens"]})
    res = check_answers(text)
    for k, v in res.items():
        if not v:
            failures.append(f"checkpoint forgets: {k}")

    # 3. shrink
    if not (stats["after_tokens"] < stats["before_tokens"]):
        failures.append("context did not shrink")
    if stats["reduction_pct"] < 50:
        failures.append(f"reduction too small: {stats['reduction_pct']}%")

    # 4. raw out
    for m in new_msgs[1:]:
        if isinstance(m, ToolMessage) and len(str(m.content).splitlines()) > 50:
            failures.append("raw log leaked into post-compact context")
            break

    print(f"before={stats['before_tokens']} after={stats['after_tokens']} reduction={stats['reduction_pct']}% via={stats['via']}")
    print(f"messages: {len(messages)} -> {len(new_msgs)}")
    if failures:
        print("VERIFY FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("VERIFY PASS: session compacted, error/tried/next remembered, raw logs out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
