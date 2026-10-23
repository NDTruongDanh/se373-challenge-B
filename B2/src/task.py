"""Shared task definition, canonical Code Mode program, and answer checker."""
from __future__ import annotations

try:  # token estimate: tiktoken when present, else char/4 heuristic (as in B1)
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(text: str) -> int:
        return len(_ENC.encode(text))

except Exception:  # pragma: no cover

    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)


TASK = (
    "Across logs/app.log, logs/test_run.log and logs/grep_noise.log: "
    "1) which 3 tests FAILED in test_run.log? "
    "2) how many lines mentioning 'refresh-token race' are in app.log? "
    "3) how many lines mentioning 'ERROR refresh-token race' in grep_noise.log? "
    "4) what is the root-cause hint (HINT), what was already tried (NOTE), "
    "and what is the next step (PLAN)? "
    "Use run_code: aggregate INSIDE the runtime and return only the findings. "
    "Count with case-insensitive substring matches over the whole file."
)

# Offline reference program: touches all 3 files, returns < 1KB.
CANONICAL_CODE = """fails = []
for line in tools.read_lines("test_run.log", 0, 8000):
    if line.startswith("FAILED"):
        name = line.split("::")[1].split()[0] if "::" in line else line
        if name not in fails:
            fails.append(name)
fails = sorted(fails)
app_errors = tools.grep_count("app.log", "ERROR auth refresh-token race")
grep_hits = tools.grep_count("grep_noise.log", "ERROR refresh-token race")
hints = tools.grep_matches("test_run.log", "HINT", 5)
notes = tools.grep_matches("test_run.log", "NOTE", 5)
plans = tools.grep_matches("test_run.log", "PLAN", 5)
result = {
    "failed_tests": fails,
    "app_error_race_lines": app_errors,
    "grep_real_signals": grep_hits,
    "hint": hints[0] if hints else "",
    "tried": notes,
    "next": plans[0] if plans else "",
}"""

EXPECTED = {
    "tests": ["test_concurrent_refresh", "test_session_expiry_retry", "test_lock_around_refresh"],
    "app_errors": 3,
    "grep_hits": 3,
    "hint_kw": ["race", "SessionStore.refresh", "no lock"],
    "tried_kw": ["TTL", "retry"],
    "next_kw": ["locking around refresh", "session.py"],
}


def check_answers(text: str) -> dict[str, bool]:
    """Strict: counts must appear on the same line as the file they describe,
    so a '3' elsewhere in the answer can't mask a wrong count."""
    import re

    lines = text.splitlines()

    def count_near(file_kw: str, n: int) -> bool:
        pat = re.compile(rf"(?i)(?:{file_kw}[^\n]*\b{n}\b|\b{n}\b[^\n]*{file_kw})")
        return any(pat.search(ln) for ln in lines)

    low = text.lower()
    return {
        "failed_tests": all(t.lower() in low for t in EXPECTED["tests"]),
        "app_error_count": count_near(r"app", EXPECTED["app_errors"]),
        "grep_count": count_near(r"grep", EXPECTED["grep_hits"]),
        "hint": any(k.lower() in low for k in EXPECTED["hint_kw"]),
        "tried": any(k.lower() in low for k in EXPECTED["tried_kw"]),
        "next": any(k.lower() in low for k in EXPECTED["next_kw"]),
    }
