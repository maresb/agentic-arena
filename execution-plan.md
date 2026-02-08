# Execution Plan

This plan is derived from `TODO.md` and `TODO_IMPROVEMENTS.md`. It sequences
work into dependency-aware phases with the required priority on UX and
observability to improve dogfooding and reduce debugging friction.

**Validation checkpoint (applies to all phases):** Before starting any phase,
confirm that each listed item is still open in the current codebase. If an
item is already implemented, mark it complete and skip it to avoid rework.

## Phase 1 — Observability & UX Baseline (Mandatory)
**Goal:** Provide a visible heartbeat and inspectable artifacts during runs.

**Items (ordered, with item-level effort):**
1. **Polling progress indicator / Polling Visibility** (TODO.md UX +
   TODO_IMPROVEMENTS.md §3) — *Effort: S*  
   Single implementation that prints `.` to stderr per polling interval.
2. **Externalize large text from state.json** (TODO.md UX) — *Effort: M*  
   Store solutions/analyses/critiques/verdicts as separate Markdown files with
   file-path pointers in `state.json`.
3. **Rearchitect the arena directory layout** (TODO.md UX) — *Effort: L*  
   Move run state to `arenas/` with numbered runs and chronologically named
   artifacts. Use a minimal chronological naming scheme here; finalize the
   full naming spec in Phase 2.

**Dependencies:** None (first phase by requirement).

**Effort (overall):** **L**

**Rationale:** These changes immediately improve dogfooding and make all later
work easier to debug and validate.

**Risks / Open Questions:**
- Backward compatibility for existing `arena/` layouts or `state.json` formats.
- Whether a migration path or dual-read support is required.

---

## Phase 2 — Artifact Naming & Archiving Consistency
**Goal:** Make artifacts stable, sortable, and aligned with the new layout.

**Items (ordered, with item-level effort):**
1. **Artifact Naming & Organization** (TODO_IMPROVEMENTS.md §1) — *Effort: M*  
   Adopt the round/phase/model/uid naming format and ensure sorting reflects
   chronological order.
2. **Stabilize archiving** (TODO.md Features) — *Effort: M*  
   Replace UUID-per-step with per-round/per-phase archiving.
3. **Restructure phase_progress** (TODO.md Features) — *Effort: S/M*  
   Separate verify progress from agent alias keys for clarity.

**Dependencies:** Phase 1 (layout + externalized artifacts). Archiving changes
depend on the new directory structure.

**Effort (overall):** **M**

**Rationale:** Once the directory structure exists, make the files predictable
and resilient to retries.

**Risks / Open Questions:**
- Need to preserve or migrate older archive formats.
- Interaction between archive naming and externalized artifact pointers.

---

## Phase 3 — Reliability & Correctness
**Goal:** Eliminate restart-related bugs and enforce guardrails.

**Items (ordered, with item-level effort):**
1. **save_state path bug in phases** (TODO.md Bugs) — *Effort: S*  
   Thread `state_path` through phase functions to respect `--arena-dir`.
2. **Make verify idempotent on restart** (TODO.md Bugs +
   TODO_IMPROVEMENTS.md §4) — *Effort: M*  
   Persist verify-sent marker, judge ID, and previous message count.
3. **Fix follow-up resume for SENT agents** (TODO.md Bugs) — *Effort: M*  
   Use persisted message counts instead of status-only polling.
4. **Enforce consensus score >= 8 in code** (TODO.md Bugs) — *Effort: S*  
   Validate `convergence_score` and re-prompt on malformed verdicts.

**Dependencies:** Phase 1 (state schema changes); Phase 2 if `phase_progress`
or archiving affects persisted state.

**Effort (overall):** **M**

**Rationale:** Correctness and idempotency are prerequisites for safe feature
expansion and long-running arenas.

**Risks / Open Questions:**
- Semantics of verify markers and message counts across retries.
- Whether consensus enforcement should reprompt or fail fast.

---

## Phase 4 — Workflow & Collaboration Quick Wins
**Goal:** Improve collaboration and output usability with low-to-medium effort.

**Items (ordered, with item-level effort):**
1. **Merge Strategy** (TODO_IMPROVEMENTS.md §2) — *Effort: S*  
   Print PR/compare URL for the winning branch in CLI output and `report.md`.
2. **Let agents view each other's branches** (TODO.md UX) — *Effort: M*  
   Use `git fetch` for sibling branches to avoid pasting large texts.
3. **Configurable model list** (TODO.md Features) — *Effort: M*  
   Add `--models` CLI flag with validation against available models.
4. **Treat verify-command results as first-class outputs** (TODO.md Features)
   — *Effort: M*  
   Store outputs and allow advisory vs. gating modes.
5. **Wire RETRY_PROMPT into phases** (TODO.md Features) — *Effort: S/M*  
   Send format-reminder follow-up on missing `<solution>` tags.

**Dependencies:** Phases 1–3 (stable artifacts and restart semantics).

**Effort (overall):** **L**

**Rationale:** These items deliver immediate workflow value with moderate risk,
so they should land before large-scale scaling work.

**Risks / Open Questions:**
- Branch discovery conventions and permissions for cross-agent `git fetch`.
- How verify-command gating interacts with consensus enforcement.

---

## Phase 5 — Scaling & Long-Run Stability
**Goal:** Prevent context exhaustion and support larger tasks.

**Items (ordered, with item-level effort):**
1. **Context management** (TODO.md Features + TODO_IMPROVEMENTS.md §5)
   — *Effort: XL*  
   Summarization, diff-only views, and fresh-agent-per-round strategies.
2. **Token usage monitoring** (TODO.md Features) — *Effort: M*  
   Log approximate token counts per follow-up and warn near limits.
3. **Webhook support** (TODO.md Features) — *Effort: L/XL*  
   Replace polling if the API supports webhooks.

**Dependencies:** Phases 1–4 (stable prompts, artifacts, and workflows).

**Effort (overall):** **XL**

**Rationale:** These are high-impact but higher-risk changes that require a
stable base and careful validation.

**Risks / Open Questions:**
- API support and reliability for webhooks.
- Trade-offs between summarization cost and fidelity.

---

## Phase 6 — Code Quality, Testing, and Infrastructure
**Goal:** Improve maintainability, reliability, and CI confidence.

**Items (ordered, with item-level effort):**
1. **Remove dead code** (TODO.md Code quality) — *Effort: S*
2. **Consolidate _is_assistant_message** (TODO.md Code quality) — *Effort: S*
3. **Add request timeouts** (TODO.md Code quality) — *Effort: S/M*
4. **CI pipeline** (TODO.md Code quality) — *Effort: M*
5. **Expand test coverage** (TODO.md Code quality) — *Effort: M/L*
6. **Integration test harness** (TODO.md Code quality) — *Effort: L*
7. **Cost tracking** (TODO.md Code quality) — *Effort: M*

**Dependencies:** Phases 1–5 (behaviors stabilized).

**Effort (overall):** **L**

**Rationale:** Quality investments pay off most once interfaces stabilize; CI
should land before test expansion to shorten feedback loops.

**Risks / Open Questions:**
- Availability of a stable test API environment for integration tests.
- Cost tracking data sources and accuracy.

---

## Phase 7 — Documentation & Runbook
**Goal:** Ensure users and operators can run, debug, and trust the system.

**Items (ordered, with item-level effort):**
1. **Update README "Current state"** (TODO.md Documentation) — *Effort: S*
2. **Document Basic Auth, model availability, restart semantics, verify-command
   behavior** (TODO.md Documentation) — *Effort: S*
3. **Add a runbook / troubleshooting section** (TODO.md Documentation)
   — *Effort: S*

**Dependencies:** Phases 1–6 (final behaviors documented).

**Effort (overall):** **S**

**Rationale:** Documentation must reflect the final system behavior.

**Risks / Open Questions:**
- Any additional operational guidance needed after webhook support or CI.
