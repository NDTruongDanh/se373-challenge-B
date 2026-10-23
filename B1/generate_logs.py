"""Synthetic log generator for B1.

Creates a LONG session fixture with tool-output bloat (slide 19):
  logs/app.log       ~2,000 lines (INFO noise + duplicated WARN + real ERRORs)
  logs/test_run.log  ~7,000 lines (pass noise + 3 buried FAILs + root-cause hint)
  logs/grep_noise.log ~1,500 lines (retry noise for grep tool)

Buried ground truth (must survive compaction):
  - failing: test_concurrent_refresh, test_session_expiry_retry, test_lock_around_refresh
  - cause hint: "locking around refresh in session.py:refresh (no lock held)"
  - tried & failed: "increasing token TTL did not help", "naive retry loop x3"
  - next: "inspect locking around refresh in dummy_app/session.py"
  - constraint: "keep API backward compatible (login/refresh signatures unchanged)"
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

BASE = Path(__file__).parent.parent / "logs"  # repo root logs/ (shared with B2)

FAILURES = [
    "test_concurrent_refresh",
    "test_session_expiry_retry",
    "test_lock_around_refresh",
]

CAUSE_HINT = "root cause hint: race in SessionStore.refresh() — read-modify-write with no lock held (see dummy_app/session.py:refresh)"
TRIED = [
    "attempt: increasing token TTL to 3600s did not help (still 2 tokens issued)",
    "attempt: naive retry loop x3 did not help (duplicates persist under concurrency)",
]
CONSTRAINT = "constraint: keep API backward compatible (login/refresh signatures unchanged)"
NEXT = "next_action: inspect locking around refresh in dummy_app/session.py"


def write_app_log(path: Path, n: int = 2000, seed: int = 7) -> None:
    rng = random.Random(seed)
    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            ts = f"2026-10-23T10:{i // 60:02d}:{i % 60:02d}Z"
            r = rng.random()
            if i in (400, 1200, 1750):
                f.write(f"{ts} ERROR auth refresh-token race: duplicate token issued for user u_{i} (concurrent refresh)\n")
            elif r < 0.80:
                f.write(f"{ts} INFO  req={i:05d} method=GET /api/health latency={rng.randint(1, 40)}ms\n")
            elif r < 0.93:
                # duplicated warning (DROP candidate during compaction)
                f.write(f"{ts} WARN  slow query shard={rng.randint(1, 8)} retryable=true (duplicate noise {i % 5})\n")
            else:
                f.write(f"{ts} INFO  req={i:05d} method=POST /api/login ok user=u_{i}\n")
        f.write(f"SUMMARY app.log: {CONSTRAINT}\n")


def write_test_log(path: Path, n: int = 7000, seed: int = 13) -> None:
    rng = random.Random(seed)
    fail_at = {900: FAILURES[0], 3400: FAILURES[1], 6100: FAILURES[2]}
    with path.open("w", encoding="utf-8") as f:
        f.write("pytest dummy_app/ -x -q (simulated large output)\n")
        for i in range(n):
            if i in fail_at:
                name = fail_at[i]
                f.write(f"FAILED dummy_app/test_auth.py::{name} — AssertionError: concurrent refresh issued 2 tokens, expected 1\n")
                if i == 6100:
                    f.write(f"HINT {CAUSE_HINT}\n")
                    for line in TRIED:
                        f.write(f"NOTE {line}\n")
                    f.write(f"PLAN {NEXT}\n")
            elif rng.random() < 0.985:
                f.write(f"PASSED dummy_app/test_auth.py::test_ok_{i:04d} ({rng.randint(1, 9)}ms)\n")
            else:
                f.write(f"WARNING flaky timing jitter {rng.random():.4f} (noise, safe to drop)\n")
        f.write(f"SUMMARY 3 failed, {n - 3} passed. {CONSTRAINT}. {NEXT}.\n")


def write_grep_noise(path: Path, n: int = 1500, seed: int = 21) -> None:
    rng = random.Random(seed)
    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            if i % 500 == 250:
                f.write(f"match {i}: ERROR refresh-token race duplicate token (real signal)\n")
            else:
                f.write(f"match {i}: TODO cleanup retryable={rng.randint(0, 1)} (noise, safe to drop)\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--app-lines", type=int, default=2000)
    p.add_argument("--test-lines", type=int, default=7000)
    p.add_argument("--grep-lines", type=int, default=1500)
    args = p.parse_args()
    BASE.mkdir(parents=True, exist_ok=True)
    write_app_log(BASE / "app.log", args.app_lines)
    write_test_log(BASE / "test_run.log", args.test_lines)
    write_grep_noise(BASE / "grep_noise.log", args.grep_lines)
    sizes = {f.name: f.stat().st_size for f in BASE.glob("*.log")}
    total = sum(sizes.values())
    print(f"wrote logs/ {sizes} total_bytes={total}")


if __name__ == "__main__":
    main()
