# Structured checkpoint (B1 compact)
- created: 2026-10-23T09:14:09+00:00 via=llm before_tokens=126172 after_tokens=609

goal: Investigate the refresh-token race condition.
current_state: 3 failed, 6997 passed; logs/app.log and logs/test_run.log not found
constraints: keep API backward compatible (login/refresh signatures unchanged)
findings:
- FAILED dummy_app/test_auth.py::test_concurrent_refresh — AssertionError: concurrent refresh issued 2 tokens, expected 1
- FAILED dummy_app/test_auth.py::test_session_expiry_retry — AssertionError: concurrent refresh issued 2 tokens, expected 1
- FAILED dummy_app/test_auth.py::test_lock_around_refresh — AssertionError: concurrent refresh issued 2 tokens, expected 1
- HINT root cause hint: race in SessionStore.refresh() — read-modify-write with no lock held (see dummy_app/session.py:refresh)
failed_attempts:
- NOTE attempt: increasing token TTL to 3600s did not help (still 2 tokens issued)
- NOTE attempt: naive retry loop x3 did not help (duplicates persist under concurrency)
files: [dummy_app/session.py, dummy_app/test_auth.py, logs/app.log, logs/test_run.log]
next_action: inspect locking around refresh in dummy_app/session.py
