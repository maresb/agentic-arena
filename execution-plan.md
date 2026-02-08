# Execution Plan

This plan is derived from `TODO.md` and `TODO_IMPROVEMENTS.md`. It sequences
work into dependency-aware phases with the required priority on UX and
observability to improve dogfooding and reduce debugging friction.

## Phase 1 — Observability & UX Feedback Loop
**Goal:** Make long-running runs visibly alive and make artifacts readable and
discoverable during dogfooding.

**Items (from TODOs):**
- **Polling progress indicator** (TODO.md — UX and observability).
- **Polling Visibility** (TODO_IMPROVEMENTS.md §3) — same mechanism as above;
  implement once with shared behavior.
- **Externalize large text from state.json** (TODO.md — UX and observability).
- **Rearchitect the arena directory layout** (TODO.md — UX and observability).
- **Let agents view each other's branches** (TODO.md — UX and observability).

**Dependencies:** None (first phase by requirement).

**Effort:** **L**

**Rationale:** These changes make the system immediately more inspectable and
reduce "is it hung?" uncertainty. Clear artifacts and visible progress are
prerequisites for safely iterating on correctness and features.

**Risks / Open Questions:**
- Backward compatibility for existing `arena/` layouts or `state.json` formats.
- Whether a migration path or dual-read support is required.
- Branch discovery and naming conventions for cross-agent `git fetch`.

---

## Phase 2 — Artifact Organization & Archiving Consistency
**Goal:** Make archived artifacts stable, sortable, and aligned with the new
arena layout.

**Items (from TODOs):**
- **Artifact Naming & Organization** (TODO_IMPROVEMENTS.md §1).
- **Stabilize archiving** (TODO.md — Features).
- **Restructure phase_progress** (TODO.md — Features).

**Dependencies:** Phase 1 (new arena layout + externalized artifacts).

**Effort:** **M**

**Rationale:** With the observability foundation in place, unify naming and
archiving so that files are predictable, sortable, and resilient to retries.

**Risks / Open Questions:**
- Need to preserve or migrate older archive formats.
- How to represent verify progress cleanly alongside per-agent progress.
- Interaction between archive naming and externalized artifact pointers.

---

## Phase 3 — Correctness & Restart Safety
**Goal:** Eliminate restart-related correctness bugs and enforce guardrails.

**Items (from TODOs):**
- **save_state path bug in phases** (TODO.md — Bugs and correctness).
- **Make verify idempotent on restart** (TODO.md + TODO_IMPROVEMENTS.md §4).
- **Fix follow-up resume for SENT agents** (TODO.md — Bugs and correctness).
- **Enforce consensus score >= 8 in code** (TODO.md — Bugs and correctness).

**Dependencies:** Phase 1 (state layout changes); Phase 2 if phase_progress or
archiving changes affect persisted state.

**Effort:** **M**

**Rationale:** Correctness and idempotency are essential before deeper feature
work; these fixes prevent duplicated prompts and inconsistent verdicts.

**Risks / Open Questions:**
- Precise semantics of "verify sent" markers and message counts across retries.
- Whether consensus enforcement should reprompt or fail fast.

---

## Phase 4 — Feature Expansion & Workflow Improvements
**Goal:** Add high-value features that improve workflow flexibility and scaling.

**Items (from TODOs):**
- **Configurable model list** (TODO.md — Features).
- **Treat verify-command results as first-class outputs** (TODO.md — Features).
- **Wire RETRY_PROMPT into phases** (TODO.md — Features).
- **Context management** (TODO.md — Features + TODO_IMPROVEMENTS.md §5).
- **Token usage monitoring** (TODO.md — Features).
- **Webhook support** (TODO.md — Features).
- **Merge Strategy** (TODO_IMPROVEMENTS.md §2).

**Dependencies:** Phases 1–3 (observability, state/archiving stability, and
correctness).

**Effort:** **XL**

**Rationale:** These features add flexibility and scalability but depend on a
stable state/archiving model and reliable restart semantics.

**Risks / Open Questions:**
- API support for webhooks and model discovery constraints.
- Trade-offs between summarization cost vs. fidelity.
- How verify-command gating interacts with consensus enforcement.

---

## Phase 5 — Code Quality, Testing, and Infrastructure
**Goal:** Improve maintainability, reliability, and CI confidence.

**Items (from TODOs):**
- **Remove dead code** (TODO.md — Code quality).
- **Consolidate _is_assistant_message** (TODO.md — Code quality).
- **Add request timeouts** (TODO.md — Code quality).
- **Expand test coverage** (TODO.md — Code quality).
- **Integration test harness** (TODO.md — Code quality).
- **Cost tracking** (TODO.md — Code quality).
- **CI pipeline** (TODO.md — Code quality).

**Dependencies:** Phases 1–4 (stabilized behavior to lock into tests).

**Effort:** **L**

**Rationale:** Quality investments are most effective once core behaviors have
stabilized; otherwise tests and CI churn frequently.

**Risks / Open Questions:**
- Availability of a stable test API environment for integration tests.
- Cost tracking data sources and accuracy.

---

## Phase 6 — Documentation & Runbook
**Goal:** Ensure users and operators can run, debug, and trust the system.

**Items (from TODOs):**
- **Update README "Current state"** (TODO.md — Documentation).
- **Document Basic Auth, model availability, restart semantics, verify-command
  behavior** (TODO.md — Documentation).
- **Add a runbook / troubleshooting section** (TODO.md — Documentation).

**Dependencies:** Phases 1–5 (features and behaviors documented).

**Effort:** **S**

**Rationale:** Documentation must reflect the final behavior after the earlier
phases land.

**Risks / Open Questions:**
- Any additional operational guidance needed after webhook support or CI.
