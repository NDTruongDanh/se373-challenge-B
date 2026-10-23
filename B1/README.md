# B1: Compact — keep context small while the agent still gets the job done

Implements **Challenge B1 (slides 32–33)** of the _Memory, Context Engineering & Prompt Caching_ module (SE373).

**Goal:** a long debugging session full of large logs gets compacted, and the agent
still remembers the three things that matter:

1. what error is under investigation,
2. what was already tried,
3. what the next step is —

while raw logs stay out of the context.

## Contents

```
B1/
├── pyproject.toml        deps (langgraph, langchain-openai, tiktoken, dotenv) + uv venv
├── .gitignore            .venv, __pycache__, .env, archive/
(no local .env here — shared env lives at repo root: ../.env, template ../.example.env)
├── generate_logs.py      builds the synthetic fixture in ../logs/ (shared with B2)
├── dummy_app/
│   ├── session.py        buggy SessionStore: refresh() does read-modify-write
│   │                     WITHOUT holding the lock → concurrent refresh issues 2 tokens
│   └── auth.py           thin login()/refresh_token() wrapper (API must stay backward compatible)
├── src/
│   ├── config.py         loads ../.env (repo root, shared with B2), resolves API key / base URL / models / TOKEN_BUDGET
│   ├── tools.py          3 tools that deliberately produce tool-output bloat:
│   │                     read_log, grep_logs, run_tests_sim (+ RAW_CHAR_COUNTER)
│   ├── compaction.py     the compaction pipeline (see below)
│   └── agent_graph.py    LangGraph harness: agent ⇄ tools, conditional compact node
├── demo.py               end-to-end proof: long session → compact → post-compact quiz
├── verify.py             automated checks, no API key needed (heuristic path)
├── checkpoint.md         structured checkpoint produced by the last demo run
└── archive/              append-only JSONL record of each compaction (raw history lives here)
../logs/                  shared fixture (moved to repo root for B2):
  ├── app.log             ~2,000 lines: INFO noise + duplicated WARNs + 3 real ERRORs
  ├── test_run.log        ~7,000 lines: pass noise + 3 buried FAILEDs + HINT/NOTE/PLAN lines
  └── grep_noise.log      ~1,500 lines: grep matches, mostly noise
```

The ground truth buried in the logs (what a correct checkpoint must contain):

| Item                   | Value                                                                              |
| ---------------------- | ---------------------------------------------------------------------------------- |
| Failing tests          | `test_concurrent_refresh`, `test_session_expiry_retry`, `test_lock_around_refresh` |
| Root cause             | race in `SessionStore.refresh()` — read-modify-write with no lock held             |
| Already tried (failed) | increasing token TTL to 3600s; naive retry loop ×3                                 |
| Constraint             | keep API backward compatible (`login`/`refresh` signatures unchanged)              |
| Next step              | inspect locking around refresh in `dummy_app/session.py`                           |

## Setup

```powershell
cd B1
uv venv
uv sync
copy ..\.example.env ..\.env   # shared env at repo root (template: ..\.example.env), then paste your key (pre-filled in this environment)
uv run python generate_logs.py   # regenerates ../logs/
```

Connection details (`src/config.py`, `src/agent_graph.py:make_llm`):

- Base URL defaults to the direct Go inference endpoint
  `https://opencode.ai/inference/go/openai/v1` (per
  [Go docs](https://opencode.ai/docs/go/#endpoints) — override with `OPENAI_BASE_URL`).
  Auth is the Go API key (`OPENCODE_API_KEY`, fallback `OPENAI_API_KEY`).
- `x-opencode-session` is a **client-chosen** stable id per conversation (used for
  routing/prompt caching), not a server session: taken from `OPENCODE_SESSION_ID`
  when present (e.g. inside an opencode session), otherwise generated fresh per run
  (`b1-<uuid>`). Always sent, along with our own `User-Agent`.
- The `*-contributor` models only speak the **responses protocol**, so the harness builds
  `ChatOpenAI(use_responses_api=True)` and `message_text()` extracts only text blocks
  (reasoning blocks are skipped, never treated as visible text).

## Running the proof

```powershell
uv run python verify.py            # no key, no network: heuristic checkpoint (exits 0 on PASS)
uv run python demo.py --no-agent   # fully deterministic, offline: heuristic compact + checkpoint quiz
uv run python demo.py              # full live run: agent loop + LLM compact + LLM quiz.
                                   # Any LLM failure raises loudly — no silent fallbacks.
```

`demo.py --no-agent` builds a 9-message session (~224k tokens, ~600KB raw tool output),
compacts it heuristically (no network), writes `checkpoint.md`, then checks the
checkpoint text itself answers the 3 questions. The full `demo.py` instead runs the
live agent loop, compacts via LLM, and quizzes a fresh LLM call that sees **only the
checkpoint** — it must answer the 3 questions without re-reading raw logs.

## How compaction is implemented (`src/compaction.py`)

The pipeline follows: **Observe → Prune → Build → Reinject → Resume**:

**1. Observe (trigger).** `compact_node` in `agent_graph.py` estimates input tokens over
the message history on every round. If it exceeds `TOKEN_BUDGET` (default 8000),
compaction runs. Token counts come from real `usage_metadata` when an LLM responded
(slide 33: _"đo input tokens qua usage"_) plus a tiktoken (`cl100k_base`) estimate with a
char÷4 fallback, so the trigger also works with no key.

**2. Prune (deterministic, no LLM).** Two passes:

- `prune_notes()` — counts oversized tool outputs (>50 lines → TRUNCATE) and duplicate
  lines (→ DROP), and states what must be KEPT verbatim. This becomes part of the LLM prompt.
- `signal_excerpt()` — builds the evidence the LLM actually sees: the first 40 lines for
  context plus every line matching signal patterns (`FAILED`, `ERROR`, `HINT`, `NOTE`,
  `PLAN`, `SUMMARY`, `root cause`, `race`, `next_action`, …), de-duplicated, capped at
  12k chars. This matters: naively slicing the first N chars feeds the LLM only noise
  (the failure evidence sits at the _tail_ of the logs), which produced checkpoints with
  `failed_attempts: none yet`. The excerpt is the fix.

  The selective rules are slide 23 verbatim: **KEEP** decisions/constraints/failing test
  names, **TRUNCATE** unresolved errors to a few lines, **DROP** duplicate logs, concluded
  retries, and reproducible data.

**3. Build (LLM-call summary step).** `build_checkpoint_llm()` sends `COMPACT_INSTRUCTION`

- excerpt + prune notes and demands **JSON only** with exactly the 7 Structured Checkpoint
  fields from slide 22: `goal, current_state, constraints, findings, failed_attempts, files,
next_action`. The prompt pins `failed_attempts` to NOTE/attempt lines and `next_action`
  to PLAN lines (quoting, never inventing). The JSON is schema-validated (missing keys or
  unparseable output → exception).

* If the LLM call fails _or no key is configured_, `heuristic_checkpoint()` (regex over
  FAIL/HINT/NOTE/PLAN lines) fills the same schema — this is what `verify.py` and
  `demo.py --no-agent` use to prove the pipeline end-to-end with no network.
  `via` records which path ran.
* In live runs (`demo.py` without flags) compaction is **strict**: an LLM summary
  failure raises loudly instead of falling back.

**4. Reinject.** The new context is `[checkpoint.md as SystemMessage + last 2 messages]`;
oversized tail tool outputs are head/tail-truncated. In the LangGraph node this is a true
_replacement_: old messages are removed via `RemoveMessage(id)` (ids backfilled first),
so raw bloat leaves the active context. A one-line JSON record
(`ts, via, n_msgs, before_tokens`) is appended to `archive/session_full.jsonl`.

**5. Resume.** The agent continues with only the checkpoint (+ short tail) in context;
`agent_node` re-injects the checkpoint as a system message every turn with the instruction
not to re-read raw logs.

## Measured results

| Metric                 | Value                                           |
| ---------------------- | ----------------------------------------------- |
| Session before compact | 9 msgs, ~223,800 tokens, ~600KB raw tool output |
| After compact          | 3 msgs, ~500–600 tokens                         |
| Reduction              | **99.7–99.8%**                                  |
| Checkpoint path        | `via=llm` with key, `via=heuristic` without     |
| Post-compact quiz      | error ✅ / tried ✅ / next ✅, no raw leak ✅   |
