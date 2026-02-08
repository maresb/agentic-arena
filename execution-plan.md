# Execution Plan

Sequenced delivery plan for all open items in
[TODO.md](TODO.md) and [TODO\_IMPROVEMENTS.md](TODO_IMPROVEMENTS.md).

Each phase is designed so that it can be merged independently (no
half-finished features land on `main`).  Where an item appears in both
files, the canonical reference is noted.  Items that appear to already
be resolved in the current codebase are flagged with **⚠ possibly
stale** — audit before starting work.

---

## Phase 1 — UX & Observability

**Goal:** Make the orchestrator pleasant to dogfood.  Every subsequent
phase benefits from better runtime visibility and cleaner on-disk
artifacts, so this ships first.  Scope is deliberately limited to
*harness* observability (what the developer running the orchestrator
sees), not agent-side capabilities.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 1a | **Polling progress indicator** — print a single `.` to stderr on each poll tick so there is visible heartbeat without flooding the terminal | TODO.md §UX "Polling progress indicator"; TODO\_IMPROVEMENTS.md §3 "Polling Visibility" | **S** | `sys.stderr.write(".")` + flush in `wait_for_agent`, `wait_for_followup`, and the `_all_` variants in `api.py`.  No state changes required.  Must coexist with the `logging` file handler: dots go to raw stderr, structured logs go to the file.  In `--verbose` mode, suppress dots in favour of full DEBUG lines to avoid interleaving. |
| 1b | **Externalize large text from state.json** — store solutions, analyses, critiques, and verdicts as separate Markdown files; keep only relative file-path pointers in `state.json` | TODO.md §UX "Externalize large text from state.json" | **L** | Touches `ArenaState` model (new path-valued fields or a serialization hook), `save_state`/`load_state`, every call-site in `phases.py` that writes `state.solutions[alias]`, and `generate_final_report`.  Must remain backwards-compatible with existing state files (migration shim that reads inline text on load, always writes externalized form on save). |
| 1c | **Rearchitect the arena directory layout** — `arenas/<NNNN>/` with chronologically-named artifact files | TODO.md §UX "Rearchitect the arena directory layout"; TODO\_IMPROVEMENTS.md §1 "Artifact Naming & Organization" | **L** | Replaces the current single `arena/` data directory with `arenas/` containing numbered runs.  The `arena/` Python package remains code-only.  Artifact naming per §1: `{round:02d}-{phase:02d}-{phase_name}-{letter}-{model}-{uid}.md`.  Depends on 1b so that file-path pointers are already in place.  The `_archive_round` function in `orchestrator.py` is rewritten to use the new scheme. |

**Dependencies:** None (this is the first phase).

**Internal ordering:** 1a → 1b → 1c.  The polling indicator is
trivial and delivers immediate value within hours.  Externalizing text
(1b) introduces the file-path pointer mechanism that 1c builds on, so
1b must land first.

**Risks / open questions:**

- *Backwards compatibility (1b):* Existing `arena/state.json` files
  contain inline text blobs.  The load path needs a migration shim
  that detects the old format and reads inline text, while the save
  path always writes the new externalized form.
- *Package vs. data directory (1c):* The Python package is `arena/`
  and the current default `--arena-dir` is also `arena`.  Separating
  them into `arena/` (code) and `arenas/` (data) resolves the
  collision.  The default `--arena-dir` changes to `arenas/0001`.
- *Naming format (1c):* TODO.md suggests purely sequential names
  (`00_solve_agent_a.md`) while §1 proposes
  `{round}-{phase}-{name}-{letter}-{model}-{uid}.md`.  Reconcile by
  adopting §1's format (`00-01-solve-a-opus-c25c32.md`) as canonical —
  it encodes more information and still sorts chronologically.

---

## Phase 2 — Reliability & Correctness

**Goal:** Fix correctness issues that cause data loss, duplicate work,
or wrong results.  These are blockers for reliable multi-round runs and
must land before any new features.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 2a | **`save_state` path bug** — thread `state_path` through all phase functions | TODO.md §Bugs "save\_state path bug in phases" (critical) | **S** | Phase functions already accept `state_path` as a keyword arg defaulting to `"arena/state.json"`.  The bug is that the `_saver` closure or other internal helpers may use the default when `--arena-dir` is custom.  Audit every call to `save_state` and `_saver` and propagate the caller's `state_path`.  After Phase 1c changes the default, the path-threading still matters for non-default dirs. |
| 2b | **Make verify idempotent on restart** — persist verify-sent marker | TODO.md §Bugs "Make verify idempotent on restart" (high); TODO\_IMPROVEMENTS.md §4 "Verify Idempotency" | **S** | **⚠ Possibly stale.** `verify_judge` and `verify_prev_msg_count` already exist on `ArenaState`, and `step_verify` persists them before the follow-up POST.  Remaining work: (1) verify no gap exists between persisting and sending, (2) confirm restart correctly skips re-selection and re-sending, (3) add a targeted test for the crash-restart path.  §4 also mentions persisting the judge ID — already done. |
| 2c | **Fix follow-up resume for SENT agents** — use persisted `sent_msg_counts` | TODO.md §Bugs "Fix follow-up resume for SENT agents" (high) | **S** | `step_evaluate` and `step_revise` already persist `sent_msg_counts` before sending and use them in `wait_for_all_followups`.  The gap: if the orchestrator crashes between persisting the count and actually sending the follow-up, the agent never received it, but the code skips re-sending (progress is SENT).  Fix: add a `followup_acked` boolean or re-send if no new messages arrive within a grace period. |
| 2d | **Enforce consensus score ≥ 8 programmatically** | TODO.md §Bugs "Enforce consensus score >= 8 in code" (medium) | **S** | **⚠ Possibly stale.** Already implemented in `step_verify` (lines 317–328 of `phases.py`).  Remaining: add a unit test exercising the override path and confirm behaviour when `parse_verdict` returns `convergence_score=None`. |

**Dependencies:** Phase 1 (the new directory layout changes default
paths, so 2a should target the post-1c codebase).  However, 2a can
begin in parallel with Phase 1 since the fix is about parameter
threading, not path values.

**Internal ordering:** 2a → 2c → 2b → 2d.  The path bug has the
highest blast radius (affects every phase).  Resume correctness (2c)
is next (affects evaluate and revise).  Verify idempotency (2b) and
score enforcement (2d) are lower risk and partially implemented.

**Risks / open questions:**

- *2b/2d may be fully resolved:* The current codebase has the state
  fields and the enforcement logic.  Audit before spending effort —
  may only need test coverage.
- *2c crash-gap:* The window between persisting `sent_msg_counts` and
  the actual `api.followup()` POST is the critical section.  A
  `followup_acked` flag per agent would close this gap but adds state
  complexity.  Alternative: on restart, detect "SENT but no new
  messages" and re-send the follow-up (idempotent from the agent's
  perspective since it just sees another user message).

---

## Phase 3 — Core Features (High Value)

**Goal:** Deliver features that directly improve run quality and
operator control.  Includes agent-side capabilities (branch viewing)
that were deferred from Phase 1 to keep the observability baseline
tightly scoped.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 3a | **Configurable model list** (`--models` CLI flag) | TODO.md §Features "Configurable model list" | **M** | Add a `--models` option to `init` accepting a comma-separated list (e.g. `opus,gpt`).  Validate against `api.list_models()`.  Dynamically size `ALIASES` based on the count.  Update `init_state`, `ArenaConfig`, and the `MODELS` dict in `prompts.py`. |
| 3b | **Merge strategy — print PR URL for winner** | TODO\_IMPROVEMENTS.md §2 "Merge Strategy" | **S** | At the end of `generate_final_report` and CLI output, print the GitHub compare/PR URL for the winning agent's branch.  Requires storing per-agent branch names in state during `step_solve` (the launch API likely returns this).  No auto-merge. |
| 3c | **Let agents view each other's branches** (`git fetch` instead of pasting full text) | TODO.md §UX "Let agents view each others branches" | **M** | Instead of embedding full solution text in evaluate/revise prompts, instruct agents to `git fetch` sibling branches and review diffs.  Requires per-agent branch names in state (shared prerequisite with 3b) and modifying `evaluate_prompt` / `revise_prompt`.  Token savings could be substantial for code-heavy tasks. |
| 3d | **Treat verify-command results as first-class outputs** | TODO.md §Features "Treat verify-command results as first-class outputs" | **M** | `verify_results` already exists on `ArenaState`.  Extend: (1) store structured pass/fail per command, (2) add `--verify-mode advisory|gating` flag, (3) in gating mode, override CONSENSUS to CONTINUE if any command fails, injecting failure output into the next round's prompts. |
| 3e | **Wire RETRY\_PROMPT into phases** | TODO.md §Features "Wire RETRY\_PROMPT into phases" | **S** | **⚠ Possibly stale.** `_extract_with_retry` already exists and is called in `step_solve` and `step_revise`.  Verify it's used consistently in all extraction paths.  Add test coverage for the retry path. |

**Dependencies:** Phase 2 (correctness fixes must be solid before
adding features).  3b and 3c share the prerequisite of storing
per-agent branch names (can be done once in 3b and reused by 3c).

**Internal ordering:** 3a → 3e → 3b → 3c → 3d.  Model configurability
first (unblocks multi-model testing), then the easy wins (retry
confirmation, PR URL), then branch sharing, then verify gating (most
complex).

**Risks / open questions:**

- *3c reliability:* Agents may not reliably execute `git fetch` or
  parse diffs.  Need a fallback to the paste-based approach.  Consider
  making this opt-in via `--branch-sharing` flag.
- *3b branch names:* Confirm whether the Cursor launch API returns the
  agent's working branch name.  If not, derive it from the agent ID or
  require a naming convention.
- *3d gating cascades:* If verify commands fail in gating mode and the
  loop continues, the next round's evaluate/revise prompts need the
  failure output.  Design the prompt injection before implementing.

---

## Phase 4 — Structural Features & Archiving

**Goal:** Clean up phase progress tracking, stabilize archiving, and
lay groundwork for multi-round scalability.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 4a | **Restructure `phase_progress`** — separate verify key | TODO.md §Features "Restructure phase\_progress" | **M** | Currently `phase_progress` mixes agent aliases (`agent_a`) with the string `"verify"`.  Refactor to either (1) a dedicated `verify_progress: ProgressStatus` field, or (2) a typed dict with an explicit schema.  Touches all phase functions and the `status` CLI command. |
| 4b | **Stabilize archiving** — per-round strategy | TODO.md §Features "Stabilize archiving" | **M** | Replace the UUID-per-step `_archive_round` with the deterministic naming scheme established in Phase 1c.  Archive once per round (not per `step_once` call).  Deduplicate by checking whether the artifact file already exists.  **Explicit dependency on 1c:** the naming scheme and directory structure must be in place first. |
| 4c | **Context management** — summarization, diff-only, fresh agents | TODO.md §Features "Context management"; TODO\_IMPROVEMENTS.md §5 | **XL** | Three independently valuable sub-strategies: (1) **diff-only views** — use `git diff` output instead of full file contents (synergy with 3c), (2) **fresh agents** — launch new agents per round with only necessary context, (3) **summarization** — use a cheap model to compress previous rounds.  Ship in this order; each can be a separate PR. |
| 4d | **Token usage monitoring** | TODO.md §Features "Token usage monitoring" | **M** | Log approximate token counts per follow-up (estimate from character count or use tiktoken).  Warn when approaching 100k context window.  Store cumulative counts in state for the final report. |

**Dependencies:** Phase 3 (model configurability, branch sharing).
4b explicitly depends on 1c (new directory layout and naming scheme).
4c sub-strategy (1) depends on 3c (branch sharing for diff access).

**Internal ordering:** 4a → 4b → 4d → 4c.  Restructure progress
tracking first (simplifies all subsequent phase work), then archiving,
then monitoring, then the large context management effort.

**Risks / open questions:**

- *4c scope:* Context management is XL and could expand indefinitely.
  Time-box to one sub-strategy per release.
- *4c fresh agents:* Launching fresh agents per round increases API
  cost (new VM spin-up each time).  Measure whether token savings
  outweigh the latency and cost penalty before committing.
- *4d accuracy:* Without access to actual tokenizers for each model,
  character-based estimates may be off by 2–3×.  Use tiktoken for
  OpenAI models and a conservative multiplier for others.

---

## Phase 5 — Code Quality, Testing & CI

**Goal:** Reduce tech debt, expand test coverage, and establish
automated quality gates.  CI is a force multiplier — once it exists,
every subsequent PR gets automated lint, typecheck, and test
validation.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 5a | **Remove dead code** (`extract_solution_and_analysis_from_latest`) | TODO.md §Code quality "Remove dead code" | **S** | **⚠ Possibly stale.** This function does not appear in the current codebase (`extraction.py` has `extract_solution_and_analysis` instead).  Grep to confirm, mark complete if absent. |
| 5b | **Consolidate `_is_assistant_message`** | TODO.md §Code quality "Consolidate \_is\_assistant\_message" | **S** | **⚠ Possibly stale.** `is_assistant_message` lives in `extraction.py` and is imported by `api.py`.  If `api.py` no longer has its own copy, mark complete.  Otherwise remove the duplicate and use the single import. |
| 5c | **Add request timeouts** | TODO.md §Code quality "Add request timeouts" | **S** | **⚠ Possibly stale.** `CursorCloudAPI.__init__` accepts `timeout` (default 60s) and `_request` passes it to every HTTP call via `kwargs.setdefault`.  Verify no code paths bypass `_request`; if none, mark complete. |
| 5d | **Expand test coverage** (+17 tests) | TODO.md §Code quality "Expand test coverage" | **L** | Target areas: `step` CLI command, archive logic, `step_once` edge cases, real API message format extraction, `wait_for_followup` resume, consensus score override, retry prompt path.  Write against existing test files. |
| 5e | **CI pipeline** (GitHub Actions) | TODO.md §Code quality "CI pipeline" | **M** | Lint (`ruff`), typecheck (`pyright` or `mypy`), and unit tests (`pixi run pytest`).  Install pixi via the official one-liner.  Integration tests on a separate manual-trigger schedule.  **Ship CI early within this phase** — it's a force multiplier for all remaining work. |
| 5f | **Integration test harness** | TODO.md §Code quality "Integration test harness" | **L** | `tests/integration/` suite running against the live Cursor API with a test repo.  Opt-in via env var (`ARENA_INTEGRATION=1`).  Requires a dedicated test API key as a repository secret.  Budget cap: ~$5/run using the cheapest model. |
| 5g | **Cost tracking** | TODO.md §Code quality "Cost tracking" | **M** | Estimate per-agent cost from model pricing and token counts (depends on 4d).  Store cumulative cost in state; print in the final report and CLI summary. |

**Dependencies:** Phase 4 (context management adds code paths that
need testing).  5g depends on 4d (token monitoring).  5e (CI) should
ship as early in this phase as possible.

**Internal ordering:** 5a → 5b → 5c (audit stale items, mark complete
or fix) → 5e (CI pipeline — force multiplier) → 5d (test expansion,
now validated by CI) → 5f → 5g.

**Risks / open questions:**

- *5a/5b/5c are likely stale:* All three appear resolved in the
  current codebase.  Audit first; if confirmed, mark complete and
  reclaim the effort.
- *5f API cost:* Integration tests launch real agents.  Enforce a
  budget cap and use the cheapest model.  Consider a mock-API mode for
  CI.
- *5e pixi in CI:* GitHub Actions runners need pixi installed via
  `curl -fsSL https://pixi.sh/install.sh | bash`.  Cache the pixi
  environment for faster subsequent runs.

---

## Phase 6 — Webhook Support

**Goal:** Replace polling with event-driven status updates if the
Cursor API supports webhooks.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 6a | **Webhook support** — replace polling with push notifications | TODO.md §Features "Webhook support" | **XL** | Requires: (1) a lightweight HTTP server or serverless function to receive callbacks, (2) API registration of webhook URL, (3) refactoring `wait_for_agent` / `wait_for_followup` to an event-driven model.  **Contingent on Cursor API support** — blocked indefinitely if webhooks are not available. |

**Dependencies:** Phase 5 (solid test coverage before refactoring the
polling core).

**Risks / open questions:**

- *API support:* Confirm whether the Cursor Cloud Agents API offers
  webhook registration.  If not, this phase remains blocked.
- *Deployment model:* The orchestrator is a local CLI process.
  Receiving webhooks requires a public endpoint (ngrok, cloud
  function) or falling back to polling anyway.  May not justify the
  complexity unless the orchestrator moves to a server deployment.

---

## Phase 7 — Documentation

**Goal:** Bring documentation up to date with all shipped features.
To mitigate staleness, each earlier phase should include a one-paragraph
changelog entry in the README; this phase performs a comprehensive
consistency pass.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 7a | **Update README** — reflect live API validation, new directory layout, model config, new CLI flags | TODO.md §Documentation "Update README" | **M** | Rewrite "Current state" section.  Add quick-start, configuration reference, and example output. |
| 7b | **Document Basic Auth, model availability, restart semantics, verify-command behavior** | TODO.md §Documentation "Document Basic Auth…" | **M** | Inline in README or a separate `docs/` page.  Cover: how auth works, which models are available, crash/restart behaviour, verify-command advisory vs gating modes. |
| 7c | **Runbook / troubleshooting** | TODO.md §Documentation "Add runbook/troubleshooting section" | **S** | Common failure modes: API key missing, agent stuck in RUNNING, verify timeout, `/repositories` rate limit.  One Markdown file: symptoms → causes → fixes. |

**Dependencies:** Phase 5 (features should be stable before
comprehensive documentation).  Can begin incrementally after any phase.

**Internal ordering:** 7a → 7b → 7c.  README first (most visible),
then detailed reference docs, then runbook.

**Risks / open questions:**

- *Docs drift:* Mitigated by the per-phase changelog requirement, but
  a final consistency pass is still necessary.

---

## Summary

| Phase | Name | Effort | Key deliverable |
|-------|------|--------|-----------------|
| 1 | UX & Observability | **L** | Polling dots, externalized artifacts, new directory layout |
| 2 | Reliability & Correctness | **M** | Correct state persistence, idempotent verify, safe resume |
| 3 | Core Features | **L** | Model config, PR URL, branch sharing, verify gating, retry |
| 4 | Structural Features | **XL** | Phase progress refactor, stable archiving, context management |
| 5 | Code Quality, Testing & CI | **XL** | Stale-item audit, +17 tests, CI pipeline, integration harness |
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

---

## Appendix: Possibly Stale Items

The following TODO items appear to already be resolved in the current
codebase.  Each should be audited before scheduling work:

| Item | Evidence | Action |
|------|----------|--------|
| `extract_solution_and_analysis_from_latest` (dead code) | Function not found in `extraction.py` | Grep codebase; if absent, mark complete |
| `_is_assistant_message` consolidation | `api.py` imports from `extraction.py`; no duplicate found | Confirm no second definition exists |
| Request timeouts | `CursorCloudAPI` has `timeout=60` default; `_request` passes it | Confirm no code path bypasses `_request` |
| Consensus score ≥ 8 enforcement | `step_verify` lines 317–328 override CONSENSUS when score < 8 | Add test; mark TODO complete |
| Verify idempotency fields | `verify_judge` and `verify_prev_msg_count` on `ArenaState`; persisted before POST in `step_verify` | Verify no crash-gap remains; add test |
| `RETRY_PROMPT` wiring | `_extract_with_retry` called in `step_solve` and `step_revise` | Confirm coverage is complete; add test |
