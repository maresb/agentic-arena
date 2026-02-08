# Execution Plan

This document outlines the phased execution plan for the `cursor/execution-plan-generation-c3c7` branch, derived from `TODO.md` and `TODO_IMPROVEMENTS.md`.

## Phase 1: Observability & UX Foundation (Top Priority)

**Goal:** Improve the immediate dogfooding experience by making agent progress visible and separating large artifacts from state data for easier debugging.

| Item | Source | Effort | Description |
| :--- | :--- | :--- | :--- |
| **Polling Progress Indicator** | `TODO.md`<br>`IMPROVEMENTS §3` | S | Print a single `.` to stderr on each polling event to provide a heartbeat without log flooding. |
| **Rearchitect Arena Directory** | `TODO.md`<br>`IMPROVEMENTS §1` | L | Move runs to `arenas/{run_id}/`. Implement new artifact naming convention: `{round}-{phase}-{model}-{uid}.md`. |
| **Externalize Large Text** | `TODO.md` | M | Extract solutions, analyses, and critiques from `state.json` into the separate Markdown files defined above. Store only file paths in `state.json`. |

**Rationale:** These items are critical for "dogfooding" the system. Currently, it's hard to tell if the system is hung, and `state.json` becomes unreadable with large text blobs, making debugging difficult.

**Risks/Questions:**
- Migration of existing `state.json` files (if any preservation is needed, though likely not for this dev phase).
- Ensuring downstream tools (extraction logic) correctly read from external files instead of the JSON blob.

## Phase 2: Reliability & Correctness

**Goal:** Fix critical bugs that cause crashes or inconsistent states during agent execution.

| Item | Source | Effort | Description |
| :--- | :--- | :--- | :--- |
| **Fix `save_state` Path Bug** | `TODO.md` | S | **Critical.** Thread `state_path` through phase functions so custom `--arena-dir` is respected. |
| **Verify Idempotency** | `TODO.md`<br>`IMPROVEMENTS §4` | M | **High.** Persist "verify sent" marker, judge ID, and previous message count to prevent duplicate prompts on restart. |
| **Fix Resume for SENT Agents** | `TODO.md` | M | **High.** Use persisted message counts for resumed follow-ups to prevent reading stale messages. |
| **Enforce Consensus Score** | `TODO.md` | S | **Medium.** Programmatically validate `convergence_score >= 8`. Re-prompt if verdict is malformed. |
| **Add Request Timeouts** | `TODO.md` | S | Add default timeout to `api.py` requests and retry on `ConnectionError` to prevent hanging. |

**Rationale:** These bugs directly impact the success rate of runs. The `save_state` bug causes data loss, and idempotency issues make restarts dangerous.

**Risks/Questions:**
- Handling edge cases where the API returns partial data during a crash recovery.

## Phase 3: Core Features & Workflow

**Goal:** Enable flexible configuration and complete the core interaction loop.

| Item | Source | Effort | Description |
| :--- | :--- | :--- | :--- |
| **Configurable Model List** | `TODO.md` | M | Add `--models` CLI flag. Validate against `GET /v0/models`. Remove manual `state.json` editing. |
| **Agent Branch Visibility** | `TODO.md` | M | Allow agents to `git fetch` sibling branches to view diffs instead of pasting full text. |
| **Verify Results as Outputs** | `TODO.md` | M | Store verify command results in state. Optionally use them to veto consensus. |
| **Restructure `phase_progress`** | `TODO.md` | S | Separate `"verify"` key from agent alias keys in the progress dict. |
| **Wire `RETRY_PROMPT`** | `TODO.md` | S | Trigger format-reminder follow-up when `<solution>` tags are missing. |
| **Merge Strategy (Print URL)** | `IMPROVEMENTS §2` | S | Print GitHub PR/comparison URL for the winning branch in the final report. No auto-merge. |

**Dependencies:** Phase 1 (directory structure changes might affect how we reference branches/outputs).

**Rationale:** These features make the tool usable for varied scenarios (different models) and improve the quality of the agent collaboration (branch visibility).

## Phase 4: Optimization & Scaling

**Goal:** Support longer and more complex runs without hitting token limits or performance bottlenecks.

| Item | Source | Effort | Description |
| :--- | :--- | :--- | :--- |
| **Context Management** | `TODO.md`<br>`IMPROVEMENTS §5` | XL | Implement summarization, diff-only views, or fresh-agent-per-round strategies. |
| **Stabilize Archiving** | `TODO.md` | M | Switch from UUID-per-step to per-round or per-phase archiving to reduce disk noise. |
| **Token Usage Monitoring** | `TODO.md` | S | Log token counts and warn when approaching limits. |
| **Webhook Support** | `TODO.md` | L | Optional. Replace polling with webhooks if API supports it. |

**Dependencies:** Phase 3 (Branch visibility is a prerequisite for diff-only views).

**Rationale:** Essential for runs that go beyond 1-2 rounds, where context windows become the primary constraint.

## Phase 5: Code Quality & Maintenance

**Goal:** Ensure long-term maintainability and test coverage.

| Item | Source | Effort | Description |
| :--- | :--- | :--- | :--- |
| **Test Coverage Expansion** | `TODO.md` | L | Add +17 tests for `step`, archive logic, `step_once`, message extraction. |
| **Integration Test Harness** | `TODO.md` | L | Create harness for live API testing with a test repo. |
| **Refactoring** | `TODO.md` | S | Remove `extract_solution...` dead code. Consolidate `_is_assistant_message`. |
| **CI Pipeline** | `TODO.md` | M | GitHub Actions for lint/typecheck/test. |
| **Cost Tracking** | `TODO.md` | M | Track and estimate spend per run. |

**Rationale:** Prevents regression as features are added.

## Phase 6: Documentation

**Goal:** Make the project accessible to other developers/users.

| Item | Source | Effort | Description |
| :--- | :--- | :--- | :--- |
| **Update README** | `TODO.md` | S | Reflect live API validation and "Current state". |
| **Technical Docs** | `TODO.md` | M | Document Auth, models, restart semantics, verify behavior. |
| **Runbook** | `TODO.md` | S | Troubleshooting section for common failures. |

**Rationale:** Final polish to ensure usability.
