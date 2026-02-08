# Execution Plan

Sequenced delivery plan for all open items in
[TODO.md](TODO.md) and [TODO\_IMPROVEMENTS.md](TODO_IMPROVEMENTS.md).

Each phase is designed so that it can be merged independently (no
half-finished features land on `main`).  Where an item appears in both
files, the canonical reference is noted.

---

## Phase 1 — UX & Observability

**Goal:** Make the orchestrator pleasant to dogfood.  Every subsequent
phase benefits from better runtime visibility and cleaner on-disk
artifacts, so this ships first.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 1a | **Polling progress indicator** — print `.` to stderr on each poll tick | TODO.md §UX; TODO\_IMPROVEMENTS.md §3 | **S** | One-line `sys.stderr.write(".")` + flush in `wait_for_agent`, `wait_for_followup`, and the `_all_` variants in `api.py`.  No state changes required. |
| 1b | **Externalize large text from state.json** — store solutions, analyses, critiques, and verdicts as separate Markdown files; keep only relative file-path pointers in state | TODO.md §UX | **L** | Touches `ArenaState` model (new `path`-valued fields or a helper that intercepts serialization), `save_state`/`load_state`, every call-site in `phases.py` that writes `state.solutions[alias]`, and `generate_final_report`.  Must remain backwards-compatible with existing state files (migration shim). |
| 1c | **Rearchitect arena directory layout** — `arenas/<NNNN>/` with chronologically-named artifact files | TODO.md §UX; TODO\_IMPROVEMENTS.md §1 | **L** | Replaces the current `arena/` directory (which doubles as a Python package) with an `arenas/` data directory.  Rename the package to something like `arena_cli` or keep `arena/` as code-only.  Artifact naming per §1: `{round:02d}-{phase:02d}-{phase_name}-{letter}-{model}-{uid}.md`.  Depends on 1b being done first so file-path pointers are already in place. |
| 1d | **Polling visibility — enhance logging** | TODO\_IMPROVEMENTS.md §3 | **S** | Overlaps with 1a.  Ensure the dot-printing works correctly alongside the existing `logging` handlers (dots go to raw stderr, structured logs go to the file handler).  May require a small adapter so `--verbose` mode suppresses dots in favour of full DEBUG lines. |

**Dependencies:** None (this is the first phase).

**Internal ordering:** 1a → 1d → 1b → 1c.  The polling indicator is
trivial and provides immediate value.  Externalizing text (1b) should
land before the directory rearchitecture (1c) because 1c builds on the
file-path pointer mechanism introduced by 1b.

**Risks / open questions:**

- *Backwards compatibility:* Existing `arena/state.json` files contain
  inline text blobs.  The load path needs a migration shim that detects
  the old format and reads inline text, while the save path always
  writes the new externalized form.
- *Package rename:* Moving run data out of `arena/` may break imports
  if the Python package is also called `arena`.  Decide whether to keep
  `arena/` as code-only and use `arenas/` for data, or rename the
  package.  Recommendation: keep `arena/` as the Python package, use
  `arenas/` for run data (the default `--arena-dir` changes from
  `arena` to `arenas/0001`).
- *Naming format:* The `{uid}` suffix in §1 ensures uniqueness but the
  TODO.md wording suggests purely sequential names
  (`00_solve_agent_a.md`).  Reconcile: use the §1 format
  (`00-01-solve-a-opus-c25c32.md`) as the canonical naming scheme,
  since it encodes more information and still sorts chronologically.

---

## Phase 2 — Critical Bug Fixes

**Goal:** Fix correctness issues that cause data loss, duplicate work,
or wrong results.  These must land before any new features to ensure
the orchestrator can be trusted during multi-round runs.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 2a | **`save_state` path bug** — thread `state_path` through all phase functions | TODO.md §Bugs (critical) | **S** | `step_solve`, `step_evaluate`, `step_revise`, `step_verify` already accept `state_path` as a keyword arg with a default of `"arena/state.json"`.  The bug is that some internal helpers or the `_saver` closure use the default.  Audit and propagate.  After Phase 1c, the default changes, so fix the bug first with the current default, then 1c updates the default. |
| 2b | **Verify idempotency on restart** — persist verify-sent marker | TODO.md §Bugs (high); TODO\_IMPROVEMENTS.md §4 | **S** | Partially implemented: `verify_judge` and `verify_prev_msg_count` already exist on `ArenaState`.  The remaining work is to also persist the selected judge's ID and the previous message count *atomically before* the follow-up POST (crash-gap analysis in `step_verify`).  Review the current code — it appears this is already done correctly as of the last commit.  Verify with a targeted test. |
| 2c | **Fix follow-up resume for SENT agents** — use persisted `sent_msg_counts` | TODO.md §Bugs (high) | **S** | The `wait_for_all_followups` call in `step_evaluate` and `step_revise` already uses `sent_msg_counts`.  The gap: when the orchestrator restarts and an agent's progress is `SENT`, the code re-enters the wait path but may not find the persisted count.  Add a guard: if `sent_msg_counts[alias]` is missing for a SENT agent, re-fetch the conversation length as the baseline (conservative: may re-read the old message, but won't crash). |
| 2d | **Enforce consensus score ≥ 8 programmatically** | TODO.md §Bugs (medium) | **S** | Already implemented in `step_verify` (lines 317-328 of `phases.py`).  Remaining: add a unit test that exercises the override path and confirm the `convergence_score` fallback when `parse_verdict` returns `None`. |

**Dependencies:** Phase 1 (specifically 1b/1c may change file paths,
so bug fixes to `save_state` should land on the new layout).  However,
2a can also be done in parallel with Phase 1 if the path-threading fix
is parameterized.

**Internal ordering:** 2a → 2c → 2b → 2d.  Fix the path bug first
(highest blast radius), then resume correctness, then idempotency,
then the score enforcement validation.

**Risks / open questions:**

- *2b may already be complete:* The state model has `verify_judge` and
  `verify_prev_msg_count`, and `step_verify` persists them before the
  POST.  Need to verify whether the TODO item is stale or whether
  there is still a gap (e.g. the judge ID not being checked on
  restart).
- *2c edge case:* If the orchestrator crashes between persisting
  `sent_msg_counts` and actually sending the follow-up, the count is
  stale.  The agent never received the follow-up, so
  `wait_for_followup` will time out.  Consider adding a
  "follow-up sent" boolean per agent so the re-send logic can
  distinguish "sent and waiting" from "not yet sent".

---

## Phase 3 — Core Features (High Value)

**Goal:** Deliver the features that directly improve run quality and
operator control.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 3a | **Configurable model list** (`--models` CLI flag) | TODO.md §Features | **M** | Add a `--models` option to `init` that accepts a comma-separated list (e.g. `opus,gpt`).  Validate against `api.list_models()`.  Dynamically size `ALIASES` based on the number of models.  Update `init_state` and `ArenaConfig`. |
| 3b | **Merge strategy — print PR URL for winner** | TODO\_IMPROVEMENTS.md §2 | **S** | At the end of `generate_final_report`, if consensus is reached, print the GitHub compare/PR URL for the winning agent's branch.  Requires knowing the branch name per agent (may need to store it in state during `step_solve`). |
| 3c | **Let agents view each other's branches** (`git fetch` instead of pasting) | TODO.md §UX | **M** | Instead of embedding full solution text in evaluate/revise prompts, instruct agents to `git fetch` sibling branches and review diffs.  Requires storing per-agent branch names in state and modifying `evaluate_prompt` and `revise_prompt`.  Token savings could be substantial for code-heavy tasks. |
| 3d | **Treat verify-command results as first-class outputs** | TODO.md §Features | **M** | `verify_results` already exists on `ArenaState`.  Extend: (1) store structured pass/fail per command, (2) add `--verify-mode advisory|gating` flag, (3) in gating mode, override CONSENSUS to CONTINUE if any command fails. |
| 3e | **Wire RETRY_PROMPT into phases** | TODO.md §Features | **S** | `_extract_with_retry` exists but is only called in `step_solve` and `step_revise`.  Ensure it's used consistently.  Already mostly done — confirm and add test coverage. |

**Dependencies:** Phase 2 (correctness fixes).  3a depends on 1c
(directory layout) because model count affects alias generation.  3c
depends on 1c (agents need branch names stored in the new state
format).

**Internal ordering:** 3a → 3e → 3b → 3c → 3d.  Model configurability
first (unblocks multi-model testing), then the easy wins (retry wiring,
PR URL), then the larger features.

**Risks / open questions:**

- *3c token savings vs. reliability:* Agents may not reliably execute
  `git fetch` or read diffs.  Need a fallback to the paste-based
  approach if the agent's VM can't reach the repo.  Consider making
  this opt-in via a `--branch-sharing` flag.
- *3d gating mode:* If verify commands are gating and they fail, the
  loop continues — but the agent that ran the commands may not have
  context to fix the failures.  The next round's evaluate/revise
  prompts need to include the failure output.

---

## Phase 4 — Structural Features & Archiving

**Goal:** Clean up phase progress tracking, stabilize archiving, and
lay groundwork for multi-round scalability.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 4a | **Restructure `phase_progress`** — separate verify key | TODO.md §Features | **M** | Currently `phase_progress` mixes agent aliases (`agent_a`) with the string `"verify"`.  Refactor: either (1) add a dedicated `verify_progress: ProgressStatus` field, or (2) use a typed dict with an explicit schema.  Touches all phase functions and the `status` CLI command. |
| 4b | **Stabilize archiving** — per-round strategy | TODO.md §Features | **M** | Replace the UUID-per-step `_archive_round` with a deterministic naming scheme (already defined in Phase 1c).  Archive once at the end of each round, not after every `step_once`.  Deduplicate by checking whether the artifact file already exists. |
| 4c | **Context management** — summarization, diff-only, fresh agents | TODO.md §Features; TODO\_IMPROVEMENTS.md §5 | **XL** | This is the largest single item.  Three sub-strategies: (1) summarize previous rounds via a cheap model call before pasting into prompts, (2) use `git diff` output instead of full file contents, (3) launch fresh agents per round instead of maintaining long conversations.  Each is independently valuable.  Recommend shipping (2) first (synergy with 3c), then (3), then (1). |
| 4d | **Token usage monitoring** | TODO.md §Features | **M** | Log approximate token counts per follow-up (estimate from character count or use tiktoken).  Warn when approaching 100k context.  Store cumulative counts in state for the final report. |

**Dependencies:** Phase 3 (model configurability, branch sharing).
4b depends on 1c (new directory layout).  4c depends on 3c (branch
sharing enables diff-only views).

**Internal ordering:** 4a → 4b → 4d → 4c.  Restructure progress
tracking first (simplifies all subsequent phase work), then archiving,
then monitoring, then the large context management effort.

**Risks / open questions:**

- *4c scope:* Context management is XL and could be split into its own
  multi-phase effort.  Recommend time-boxing to one strategy per
  release.
- *4c fresh agents:* Launching fresh agents per round increases API
  cost (new agent = new VM spin-up).  Need to measure whether the
  token savings outweigh the latency and cost penalty.
- *4d accuracy:* Without access to the actual tokenizer used by each
  model, character-based estimates may be off by 2-3x.  Consider
  calling the models' tokenizer endpoint if available, or using
  tiktoken for OpenAI models and a rough multiplier for others.

---

## Phase 5 — Code Quality & Testing

**Goal:** Reduce tech debt, improve reliability, and establish a
testing baseline for CI.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 5a | **Remove dead code** (`extract_solution_and_analysis_from_latest`) | TODO.md §Code quality | **S** | Grep for the function, confirm it's unused, delete it.  (Note: this function does not appear in the current codebase — it may have already been removed.  Verify.) |
| 5b | **Consolidate `_is_assistant_message`** | TODO.md §Code quality | **S** | `is_assistant_message` lives in `extraction.py` and is imported by `api.py`.  The TODO mentions both files having independent copies — check whether this is still the case.  If `api.py` still has its own version, remove it and use the import. |
| 5c | **Add request timeouts** | TODO.md §Code quality | **S** | Already implemented: `CursorCloudAPI.__init__` accepts `timeout` (default 60s), and `_request` passes it to every call.  Verify the TODO is stale; if so, mark complete.  If there are code paths that bypass `_request`, fix them. |
| 5d | **Expand test coverage** (+17 tests) | TODO.md §Code quality | **L** | Target areas: `step` CLI command, archive logic, `step_once` edge cases, real API message format, `wait_for_followup` resume.  Write tests against the existing test files (`test_phases.py`, `test_orchestrator.py`, etc.). |
| 5e | **Integration test harness** | TODO.md §Code quality | **L** | A `tests/integration/` suite that runs against the live Cursor API with a test repo.  Requires a dedicated test API key (stored as a secret) and a small public repo.  Should be opt-in (skipped by default, enabled via `--integration` or env var). |
| 5f | **Cost tracking** | TODO.md §Code quality | **M** | Estimate per-agent cost from model pricing tables and token counts (depends on 4d).  Store cumulative cost in state and print in the final report. |
| 5g | **CI pipeline** (GitHub Actions) | TODO.md §Code quality | **M** | Lint (`ruff`), typecheck (`pyright`/`mypy`), and unit tests (`pytest`).  Use `pixi` for environment management.  Integration tests run on a separate schedule or manual trigger. |

**Dependencies:** Phase 4 (context management may add new code paths
that need testing).  5f depends on 4d (token monitoring).  5g depends
on 5d (need tests to run in CI).

**Internal ordering:** 5a → 5b → 5c → 5d → 5g → 5e → 5f.  Quick
cleanups first, then the test expansion, then CI, then integration
tests and cost tracking.

**Risks / open questions:**

- *5a/5b/5c may be stale:* The current codebase already has timeouts,
  a single `is_assistant_message`, and no
  `extract_solution_and_analysis_from_latest`.  These TODOs may have
  been resolved during the live testing session.  Audit before
  starting.
- *5e API cost:* Integration tests that launch real agents cost money.
  Budget a cap (e.g. $5/run) and use the cheapest available model.
- *5g pixi in CI:* GitHub Actions runners don't have pixi pre-installed.
  The CI workflow needs to install it first (one-liner via the official
  installer).

---

## Phase 6 — Webhook Support

**Goal:** Replace polling with event-driven status updates if the
Cursor API supports webhooks.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 6a | **Webhook support** — replace polling with push notifications | TODO.md §Features | **XL** | Requires: (1) a lightweight HTTP server (or use a serverless function) to receive webhook callbacks, (2) API registration of the webhook URL, (3) refactoring `wait_for_agent` / `wait_for_followup` to use an event-driven model.  This is speculative — the Cursor API may not support webhooks yet. |

**Dependencies:** Phase 5 (needs solid test coverage before
refactoring the polling core).

**Risks / open questions:**

- *API support:* Confirm whether the Cursor Cloud Agents API supports
  webhooks.  If not, this phase is blocked indefinitely.
- *Deployment model:* The orchestrator currently runs as a local CLI
  process.  Receiving webhooks requires either a public endpoint
  (ngrok, cloud function) or a local polling fallback.  May not be
  worth the complexity unless the orchestrator moves to a server
  deployment.

---

## Phase 7 — Documentation

**Goal:** Bring documentation up to date with all shipped features.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 7a | **Update README** — reflect live API validation, new directory layout, model config | TODO.md §Documentation | **M** | Rewrite "Current state" section.  Add quick-start, configuration reference, and example output. |
| 7b | **Document Basic Auth, model availability, restart semantics, verify-command behavior** | TODO.md §Documentation | **M** | Can be inline in README or a separate `docs/` page.  Cover: how auth works, which models are available, what happens on crash/restart, how verify commands work. |
| 7c | **Runbook / troubleshooting** | TODO.md §Documentation | **S** | Common failure modes: API key missing, agent stuck in RUNNING, verify timeout, rate limits on `/repositories`.  One Markdown file with symptoms → causes → fixes. |

**Dependencies:** Phase 5 (features should be stable before
documenting them).  Documentation can be written incrementally after
each phase, but a dedicated pass at the end ensures consistency.

**Internal ordering:** 7a → 7b → 7c.  README first (most visible),
then detailed docs, then runbook.

**Risks / open questions:**

- *Docs drift:* If documentation is deferred entirely to Phase 7,
  it will be stale by the time it's written.  Mitigate by requiring
  each phase to include a one-paragraph update to README's changelog
  section.

---

## Summary

| Phase | Name | Effort | Key deliverable |
|-------|------|--------|-----------------|
| 1 | UX & Observability | **L** | Polling dots, externalized artifacts, new directory layout |
| 2 | Critical Bug Fixes | **M** | Correct state persistence, idempotent verify, safe resume |
| 3 | Core Features | **L** | Model config, PR URL, branch sharing, verify gating, retry |
| 4 | Structural Features | **XL** | Phase progress refactor, stable archiving, context management |
| 5 | Code Quality & Testing | **XL** | Dead code removal, +17 tests, integration harness, CI |
| 6 | Webhook Support | **XL** | Event-driven polling (contingent on API support) |
| 7 | Documentation | **M** | README, auth/restart docs, runbook |

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6
                                                     │
                                                     ▼
                                                  Phase 7
```

Phases 6 and 7 are semi-independent: documentation can begin as soon
as Phase 5 stabilizes, and webhook support is contingent on external
API availability.  All other phases are strictly sequential.
