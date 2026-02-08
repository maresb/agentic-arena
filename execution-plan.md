# Execution Plan

Sequenced delivery plan for all open items in
[TODO.md](TODO.md) and [TODO_IMPROVEMENTS.md](TODO_IMPROVEMENTS.md).

Each phase is designed so that it can be merged independently (no
half-finished features land on `main`).  Where an item appears in both
files, the canonical reference is noted.

**Validation gate:** Before starting any phase, audit its items against
the current codebase to confirm they are still open.  Items marked
**\[Verify + Test\]** appear to already be partially or fully
implemented — the work is to *confirm* correctness and add test
coverage, not to reimplement.  See the Appendix for evidence.
After the audit, **re-estimate effort** for the phase: if stale items
collapse to zero, adjust sprint capacity accordingly.

---

## Phase 0 — Agent Branch Visibility

**Goal:** Give agents access to each other's branches so the
evaluate/revise/verify loop operates on full committed work, not just
conversation-extracted summaries.

**Motivation (from dogfooding):** The first arena run revealed that
agents commit detailed deliverables to their branches (94–288 lines)
but the evaluate prompts only include conversation-extracted summaries
(1–37 lines, capturing 5–29% of actual content).  Agents critiqued
each other's summaries, not their real work.  One agent's plan was
called "truncated" when its branch file was actually complete.  Fixing
this is the single highest-impact improvement to consensus quality.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 0a | **Capture agent branch names** — store `branchName` from the Cursor API launch response | Dogfooding finding; enables TODO.md §UX "Let agents view each others branches" | **S** | Add `branch_names: dict[str, str]` to `ArenaState`.  In `step_solve`, extract `target.branchName` from the `launch()` response and persist it.  The Cursor API returns this field in agent responses. |
| 0b | **Add branch hints to prompts** — tell agents each other's branch names in evaluate, revise, and verify prompts | Dogfooding finding | **S** | Add an optional `branch_names` parameter to `evaluate_prompt()`, `revise_prompt()`, and `verify_prompt()`.  When present, append a block: "Each agent's full work is committed to their branch.  If a summary above seems incomplete, run `git fetch origin <branch>` and inspect their commits." with per-agent branch names.  Omit the block when branch names are absent (backward-compatible). |
| 0c | **Thread branch names through phases** — pass captured branch names to prompt functions | Dogfooding finding | **S** | In `step_evaluate`, `step_revise`, and `step_verify`, pass `state.branch_names` when calling prompt functions.  Requires `branch_names` to already be captured in 0a. |

**Dependencies:** None (this is the first phase).

**Internal ordering:** 0a → 0b → 0c.  Branch name capture first,
then prompt changes, then wiring.  All three are S-effort and can
ship as a single PR.

**Risks / open questions:**

- *Branch name availability:* The `branchName` field may be absent in
  some API responses (e.g., if the agent hasn't created a branch yet).
  Handle gracefully by omitting branch hints when names are missing.
- *Agent compliance:* Agents might not always `git fetch` even when
  instructed.  But the prompt explicitly tells them to do so when
  summaries look incomplete, and frontier models reliably follow
  such instructions.
- *Conversation extraction unchanged:* `state.solutions` still
  contains conversation-extracted summaries.  This is acceptable —
  agents now have a way to access the full content on demand.  A
  future optimization could replace pasted summaries with branch-only
  references, but that's a separate change (see Phase 3c).

---

## Phase 1 — Observability & UX Foundation

**Goal:** Establish a clean, observable debugging baseline for
dogfooding.  Every subsequent phase benefits from better runtime
visibility and cleaner on-disk artifacts, so this ships first.  Scope
is deliberately limited to *harness* observability (what the developer
running the orchestrator sees), not agent-side capabilities.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 1a | **Polling progress indicator** — print a single `.` to stderr on each poll tick so there is a visible heartbeat without flooding the terminal | TODO.md §UX "Polling progress indicator"; TODO_IMPROVEMENTS.md §3 "Polling Visibility" | **S** | `sys.stderr.write(".")` + flush in `wait_for_agent`, `wait_for_followup`, and the `_all_` variants in `api.py`.  No state changes required.  Dots go to raw stderr; structured logs go to the file handler.  In `--verbose` mode, suppress dots in favour of full DEBUG lines to avoid interleaving. |
| 1b | **Externalize large text from state.json** — store solutions, analyses, critiques, and verdicts as separate Markdown files; keep only relative file-path pointers in `state.json` | TODO.md §UX "Externalize large text from state.json" | **L** | Touches `ArenaState` model (new path-valued fields or a serialization hook), `save_state`/`load_state`, every call-site in `phases.py` that writes `state.solutions[alias]`, and `generate_final_report`.  Must remain backwards-compatible with existing state files (migration shim: read inline text on load, always write externalized form on save). |
| 1c | **Rearchitect arena directory layout** — `arenas/<NNNN>/` with chronologically-named artifact files | TODO.md §UX "Rearchitect the arena directory layout"; TODO_IMPROVEMENTS.md §1 "Artifact Naming & Organization" | **L** | Replaces the current `arena/` data directory with `arenas/` containing numbered runs.  The `arena/` Python package remains code-only.  Artifact naming per §1: `{round:02d}-{phase:02d}-{phase_name}-{letter}-{model}-{uid}.md`.  Depends on 1b so file-path pointers are already in place.  Rewrites `_archive_round` in `orchestrator.py`. |

**Dependencies:** Phase 0 (branch visibility improves any arena run
used to implement this phase).

**Internal ordering:** 1a → 1b → 1c.  The polling indicator is
trivial and delivers immediate value within hours.  Externalizing text
(1b) introduces the file-path pointer mechanism that 1c builds on.

**Risks / open questions:**

- *Backwards compatibility (1b):* Existing `arena/state.json` files
  contain inline text blobs.  The load path needs a migration shim
  that detects the old format and reads inline text, while the save
  path always writes the new externalized form.  Mitigate with a
  dedicated migration test.
- *Package vs. data directory (1c):* The Python package is `arena/`
  and the current default `--arena-dir` is also `arena`.  Separating
  them into `arena/` (code) and `arenas/` (data) resolves the
  collision.  The default `--arena-dir` changes to `arenas/0001`,
  which is a breaking CLI change.
- *Naming format (1c):* TODO.md suggests sequential names
  (`00_solve_agent_a.md`) while §1 proposes
  `{round}-{phase}-{name}-{letter}-{model}-{uid}.md`.  Adopt §1's
  format (`00-01-solve-a-opus-c25c32.md`) as canonical — it encodes
  more information and still sorts chronologically.

---

## Phase 2 — Reliability & Correctness

**Goal:** Fix correctness bugs that cause data loss, duplicate work,
or wrong results, and stabilize the archiving mechanism while the
Phase 1 directory layout changes are fresh.  These are blockers for
reliable multi-round runs and must land before any new features.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 2a | **`save_state` path bug** — thread `state_path` through all phase functions | TODO.md §Bugs "save_state path bug in phases" (critical) | **S** | Phase functions accept `state_path` as a keyword arg defaulting to `"arena/state.json"`.  The bug is that the `_saver` closure or other internal helpers may use the default when `--arena-dir` is custom.  Audit every call to `save_state` and `_saver`; propagate the caller's `state_path`. |
| 2b | **Fix follow-up resume for SENT agents** — use persisted `sent_msg_counts` | TODO.md §Bugs "Fix follow-up resume for SENT agents" (high) | **S** | `step_evaluate` and `step_revise` persist `sent_msg_counts` before sending and use them in `wait_for_all_followups`.  The gap: if the orchestrator crashes between persisting the count and sending the follow-up, the agent never received it, but progress shows SENT.  Fix: re-send if no new messages arrive, or add a `followup_acked` flag. |
| 2c | **Make verify idempotent on restart** | TODO.md §Bugs "Make verify idempotent on restart" (high); TODO_IMPROVEMENTS.md §4 | **S** | **\[Verify + Test\]** `verify_judge` and `verify_prev_msg_count` already exist on `ArenaState`, and `step_verify` persists them before the follow-up POST.  Confirm: (1) no gap between persisting and sending, (2) restart correctly skips re-selection and re-sending.  Add a targeted crash-restart test. |
| 2d | **Enforce consensus score ≥ 8 programmatically** | TODO.md §Bugs "Enforce consensus score >= 8 in code" (medium) | **S** | **\[Verify + Test\]** Already implemented in `step_verify` (lines 317–328 of `phases.py`): overrides CONSENSUS to CONTINUE when `convergence_score < 8`.  Add a unit test exercising the override path and confirm behaviour when `convergence_score` is `None`. |
| 2e | **Stabilize archiving** — per-round strategy | TODO.md §Features "Stabilize archiving" | **M** | Replace the UUID-per-step `_archive_round` with the deterministic naming scheme from Phase 1c.  Archive once per round, not per `step_once` call.  Deduplicate by checking whether the artifact file already exists.  **Hard dependency on 1c** — the naming scheme and directory structure must be in place. |

**Dependencies:** Phase 1 (2a targets the post-1c codebase; 2e
requires the 1c directory layout).  2a can begin in parallel with
Phase 1 since the fix is about parameter threading, not path values.

**Internal ordering:** 2a → 2b → 2c → 2d → 2e.  Path bug first
(highest blast radius), then resume correctness, then the two
verify-and-test items, then archiving (depends on all layout work
being complete).

**Risks / open questions:**

- *2c/2d may be fully resolved:* The codebase has the state fields and
  enforcement logic.  Audit before spending effort — may only need
  test coverage.
- *2b crash-gap:* The window between persisting `sent_msg_counts` and
  the `api.followup()` POST is the critical section.  On restart,
  detect "SENT but no new messages" and re-send (idempotent from the
  agent's perspective — it just sees another user message).
- *2e naming alignment:* Archiving must use exactly the naming scheme
  from 1c.  If 1c's naming is revised during review, 2e needs
  updating.

---

## Phase 3 — Core Features & Workflow

**Goal:** Deliver features that improve run quality, operator control,
and workflow.  Includes agent-side capabilities (branch viewing) and
low-effort workflow wins (merge strategy PR URL) that were deferred
from Phase 1 to keep the observability baseline tight.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 3a | **Configurable model list** (`--models` CLI flag) | TODO.md §Features "Configurable model list" | **M** | Add `--models` to `init` accepting a comma-separated list (e.g. `opus,gpt`).  Validate against `api.list_models()`.  Dynamically size `ALIASES`.  Update `init_state`, `ArenaConfig`, and `MODELS` in `prompts.py`. |
| 3b | **Merge strategy — print PR URL for winner** | TODO_IMPROVEMENTS.md §2 "Merge Strategy" | **S** | At the end of `generate_final_report` and CLI output, print the GitHub compare/PR URL for the winning agent's branch.  Uses `state.branch_names` already captured in Phase 0.  No auto-merge. |
| 3c | **Branch-only evaluation mode** (opt-in) | TODO.md §UX "Let agents view each others branches" | **M** | Phase 0 adds branch hints alongside pasted summaries.  This item goes further: in `--branch-only` mode, omit pasted solution text entirely and rely on agents fetching branches.  Reduces prompt token usage but requires agents to always `git fetch`.  Paste-based mode remains the default. |
| 3d | **Treat verify-command results as first-class outputs** | TODO.md §Features "Treat verify-command results as first-class outputs" | **M** | `verify_results` exists on `ArenaState`.  Extend: (1) structured pass/fail per command, (2) `--verify-mode advisory|gating` flag, (3) in gating mode, override CONSENSUS to CONTINUE on failure, inject failure output into next round's prompts. |
| 3e | **Wire RETRY_PROMPT into phases** | TODO.md §Features "Wire RETRY_PROMPT into phases" | **S** | **\[Verify + Test\]** `_extract_with_retry` already exists and is called in `step_solve` and `step_revise`.  Verify consistent use in all extraction paths.  Add test coverage for the retry and re-extract path. |

**Dependencies:** Phase 2 (correctness fixes).  Phase 0 (branch name
capture and prompt hints already in place).

**Internal ordering:** 3a → 3e → 3b → 3c → 3d.  Model configurability
first (unblocks multi-model testing), then the easy wins (retry
verification, PR URL), then branch-only mode, then verify gating (most
complex).

**Risks / open questions:**

- *3c reliability:* In branch-only mode, agents must `git fetch` to
  see solutions at all.  If fetching fails, the agent has no context.
  Keep paste-based mode as the default; branch-only is opt-in via
  `--branch-only`.
- *3d gating cascades:* If verify commands fail in gating mode, the
  next round's prompts need failure output.  Design prompt injection
  before implementing.

---

## Phase 4 — Optimization & Scaling

**Goal:** Support long-running multi-round sessions through context
management, token monitoring, and progress tracking improvements.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 4a | **Restructure `phase_progress`** — separate verify key | TODO.md §Features "Restructure phase_progress" | **M** | Currently `phase_progress` mixes agent aliases (`agent_a`) with the string `"verify"`.  Refactor to either (1) a dedicated `verify_progress: ProgressStatus` field, or (2) a typed dict with explicit schema.  Touches all phase functions and the `status` CLI command. |
| 4b | **Token usage monitoring** | TODO.md §Features "Token usage monitoring" | **M** | Log approximate token counts per follow-up (character-based estimate or tiktoken).  Warn when approaching 100k context.  Store cumulative counts in state for the final report. |
| 4c | **Context management** — summarization, diff-only, fresh agents | TODO.md §Features "Context management"; TODO_IMPROVEMENTS.md §5 | **XL** | Three independently valuable sub-strategies, shipped in order: (1) **diff-only views** — `git diff` output instead of full file contents (synergy with 3c), (2) **fresh agents** — new agents per round with only necessary context, (3) **summarization** — cheap model to compress previous rounds.  Each can be a separate PR. |

**Dependencies:** Phase 3 (branch sharing for diff-only views).
4c sub-strategy (1) depends on 3c.

**Internal ordering:** 4a → 4b → 4c.  Progress tracking first
(simplifies subsequent work), then monitoring (provides data for
context management decisions), then context management.

**Risks / open questions:**

- *4c scope:* XL effort that could expand indefinitely.  Time-box to
  one sub-strategy per release.
- *4c fresh agents:* New agents per round increases API cost (VM
  spin-up).  Measure token savings vs. cost/latency before committing.
- *4b accuracy:* Without actual tokenizers per model, estimates may be
  off by 2–3×.  Use tiktoken for OpenAI models and a conservative
  multiplier for others.

---

## Phase 5 — Code Quality, Testing & CI

**Goal:** Reduce tech debt, expand test coverage, and establish
automated quality gates.  CI is a force multiplier — ship it early in
this phase so every subsequent PR gets automated validation.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 5a | **Remove dead code** (`extract_solution_and_analysis_from_latest`) | TODO.md §Code quality "Remove dead code" | **S** | **\[Verify + Test\]** Function not found in the current codebase.  Grep to confirm; mark complete if absent. |
| 5b | **Consolidate `_is_assistant_message`** | TODO.md §Code quality "Consolidate _is_assistant_message" | **S** | **\[Verify + Test\]** `is_assistant_message` lives in `extraction.py` and is imported by `api.py`.  Confirm no second definition exists; mark complete if consolidated. |
| 5c | **Add request timeouts** | TODO.md §Code quality "Add request timeouts" | **S** | **\[Verify + Test\]** `CursorCloudAPI` has `timeout=60` default; `_request` passes it via `kwargs.setdefault`.  Confirm no code paths bypass `_request`; mark complete if none. |
| 5d | **CI pipeline** (GitHub Actions) | TODO.md §Code quality "CI pipeline" | **M** | Lint (`ruff`), typecheck (`pyright` or `mypy`), unit tests (`pixi run pytest`).  Install pixi via official one-liner.  Integration tests on separate manual-trigger schedule.  **Ship early** — force multiplier for all remaining items. |
| 5e | **Expand test coverage** (+17 tests) | TODO.md §Code quality "Expand test coverage" | **L** | Target areas: `step` CLI command, archive logic, `step_once` edge cases, real API message format extraction, `wait_for_followup` resume, consensus score override, retry prompt path.  Write against existing test files; validated by CI from 5d. |
| 5f | **Integration test harness** | TODO.md §Code quality "Integration test harness" | **L** | `tests/integration/` suite against live Cursor API with a test repo.  Opt-in via env var (`ARENA_INTEGRATION=1`).  Requires a dedicated API key as a repository secret.  Budget cap: ~$5/run, cheapest model. |
| 5g | **Cost tracking** | TODO.md §Code quality "Cost tracking" | **M** | Estimate per-agent cost from model pricing and token counts (depends on 4b).  Store cumulative cost in state; print in final report and CLI summary. |

**Dependencies:** Phase 4 (context management adds code paths needing
tests).  5g depends on 4b (token monitoring).

**Internal ordering:** 5a → 5b → 5c (audit stale items) → 5d (CI) →
5e (test expansion, validated by CI) → 5f → 5g.

**Risks / open questions:**

- *5a/5b/5c likely stale:* All three appear resolved.  Audit first;
  reclaim the effort if confirmed.
- *5f API cost:* Each integration run costs real money.  Enforce a
  budget cap and cheapest-model policy.  Consider a mock-API mode for
  CI.
- *5d pixi in CI:* GitHub Actions runners need pixi installed.  Cache
  the pixi environment for faster subsequent runs.

---

## Phase 6 — Webhook Support

**Goal:** Replace polling with event-driven status updates if the
Cursor API supports webhooks.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 6a | **Webhook support** — replace polling with push notifications | TODO.md §Features "Webhook support" | **XL** | Requires: (1) a lightweight HTTP server or serverless function to receive callbacks, (2) API registration of webhook URL, (3) refactoring `wait_for_agent` / `wait_for_followup` to an event-driven model.  **Contingent on Cursor API support** — blocked indefinitely if unavailable. |

**Dependencies:** Phase 5 (solid test coverage before refactoring the
polling core).

**Risks / open questions:**

- *API support:* Confirm whether the Cursor Cloud Agents API offers
  webhooks.  If not, cancel this phase rather than leaving it as
  perpetual backlog.
- *Deployment model:* Receiving webhooks requires a public endpoint
  (ngrok, cloud function) or a polling fallback.  May not justify the
  complexity for a local CLI tool.

---

## Phase 7 — Documentation

**Goal:** Comprehensive documentation pass.  To mitigate staleness,
each earlier phase should include a one-paragraph changelog entry in
the README; this phase performs the final consistency pass.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| 7a | **Update README** — reflect live API validation, new directory layout, model config, new CLI flags | TODO.md §Documentation "Update README" | **M** | Rewrite "Current state" section.  Add quick-start, configuration reference, and example output. |
| 7b | **Document Basic Auth, model availability, restart semantics, verify-command behavior** | TODO.md §Documentation "Document Basic Auth…" | **M** | Inline in README or separate `docs/` page.  Cover: auth, model availability, crash/restart behaviour, verify-command advisory vs. gating modes. |
| 7c | **Runbook / troubleshooting** | TODO.md §Documentation "Add runbook/troubleshooting section" | **S** | Common failure modes: API key missing, agent stuck in RUNNING, verify timeout, `/repositories` rate limit.  Symptoms → causes → fixes. |

**Dependencies:** Phase 5 (features stable before documenting).
Can begin incrementally after any phase.

**Internal ordering:** 7a → 7b → 7c.  README first (most visible),
then detailed reference docs, then runbook.

**Risks / open questions:**

- *Docs drift:* Mitigated by per-phase changelog entries, but a final
  consistency pass is still required.

---

## Summary

| Phase | Name | Effort | Key deliverable |
|-------|------|--------|-----------------|
| 0 | Agent Branch Visibility | **S** | Branch name capture, prompt hints for cross-agent inspection |
| 1 | Observability & UX Foundation | **L** | Polling dots, externalized artifacts, new directory layout |
| 2 | Reliability & Correctness | **M** | State path fix, safe resume, verified idempotency, stable archiving |
| 3 | Core Features & Workflow | **L** | Model config, PR URL, branch-only mode, verify gating, retry |
| 4 | Optimization & Scaling | **XL** | Progress refactor, token monitoring, context management |
| 5 | Code Quality, Testing & CI | **XL** | Stale-item audit, CI pipeline, +17 tests, integration harness |
| 6 | Webhook Support | **XL** | Event-driven polling (contingent on API support) |
| 7 | Documentation | **M** | README, auth/restart docs, runbook |

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6
                                                                 │
                                                                 ▼
                                                              Phase 7
```

Phases 6 and 7 are semi-independent: documentation can begin
incrementally after any phase, and webhook support is contingent on
external API availability.  All other phases are strictly sequential.

---

## Appendix: Items Requiring Verification Before Scheduling

These TODO items appear partially or fully resolved in the current
codebase.  Each should be audited (validation gate) before scheduling
implementation work.  If confirmed resolved, the action is to add test
coverage and mark the TODO complete.

| Item | Evidence in current codebase | Recommended action |
|------|------------------------------|-------------------|
| `extract_solution_and_analysis_from_latest` (dead code) | Function not found in `extraction.py` | Grep codebase; if absent, mark complete |
| `_is_assistant_message` consolidation | `api.py` imports `is_assistant_message` from `extraction.py`; no duplicate definition found | Confirm single definition; mark complete |
| Request timeouts | `CursorCloudAPI` has `timeout=60`; `_request` passes it to all HTTP calls | Confirm no code paths bypass `_request`; mark complete |
| Consensus score ≥ 8 enforcement | `step_verify` lines 317–328 override CONSENSUS to CONTINUE when `convergence_score < 8` | Add unit test for override path; mark complete |
| Verify idempotency fields | `verify_judge` and `verify_prev_msg_count` on `ArenaState`; persisted before POST in `step_verify` | Verify no crash-gap; add crash-restart test; mark complete |
| `RETRY_PROMPT` wiring | `_extract_with_retry` called in `step_solve` and `step_revise` | Confirm all extraction paths covered; add test; mark complete |
