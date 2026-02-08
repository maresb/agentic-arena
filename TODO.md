# TODO

Tracked improvements, roughly prioritized within each section.
Items marked `[x]` were resolved during initial live testing (2026-02-08).

---

## Validated during live testing

- [x] Confirm API base URL, Basic Auth, and endpoint paths.
- [x] Validate agent lifecycle states (`CREATING`, `RUNNING`, `FINISHED`).
- [x] Confirm `GET /agents/{id}/conversation` returns `messages` with
      `type`/`text` fields (not `role`/`content`).
- [x] Single-agent smoke test (launch, poll, conversation retrieval).
- [x] Follow-up round-trip (send follow-up, poll for new messages, extract).
- [x] Two-agent dogfood run (solve + evaluate phases completed).

---

## UX and observability

- [ ] **Polling progress indicator.** Print a single `.` to stderr on each
      polling event so there is some visible heartbeat without flooding the
      terminal with log lines.
- [ ] **Externalize large text from state.json.** Solutions, analyses,
      critiques, and verdicts are large text blobs awkwardly embedded in JSON.
      Store them as separate text/Markdown files and keep only file-path
      pointers in `state.json`.
- [ ] **Rearchitect the arena directory layout.** Currently everything lives
      under a single `arena/` dir that is also a Python package.  Move run
      state into an `arenas/` directory with numbered runs (e.g.
      `arenas/0001/`).  Within each run directory, keep `state.json` plus
      usefully-named Markdown files for each artifact, named so that sorting
      by filename gives a sensible chronological order (e.g.
      `00_solve_agent_a.md`, `01_solve_agent_b.md`,
      `02_evaluate_agent_a.md`, ...).
- [ ] **Let agents view each other's branches.** Instead of pasting full
      solution text into follow-up prompts, point agents at each other's
      branches.  The cloud agent VMs can `git fetch` sibling branches, which
      may be more token-efficient and lets agents see actual diffs rather
      than free-text descriptions.

---

## Bugs and correctness (from dogfood agents)

- [ ] **`save_state` path bug in phases.** Phase functions call
      `save_state(state)` with the default path, silently ignoring a custom
      `--arena-dir`.  Thread `state_path` through as a parameter.
      *(Agent A, priority: critical)*
- [ ] **Make verify idempotent on restart.** A crash after sending the
      verify follow-up but before recording the verdict can cause a
      duplicate prompt on restart.  Persist a "verify sent" marker and
      previous message count. *(Agent B, priority: high)*
- [ ] **Fix follow-up resume for SENT agents.** Resumed SENT agents
      currently fall back to status-based polling, which can read the
      pre-follow-up assistant message.  Use persisted message counts for
      resumed follow-ups too. *(Agent B, priority: high)*
- [ ] **Enforce consensus score >= 8 in code.** Currently the judge's
      string is trusted.  Validate `convergence_score` programmatically
      and re-prompt on malformed verdicts. *(Agent B, priority: medium)*

---

## Features

- [ ] **Configurable model list.** `--models` CLI flag to specify which
      models to use and how many agents to run, with validation against
      `GET /v0/models`.  Eliminate the need for manual `state.json` editing.
- [ ] **Treat verify-command results as first-class outputs.** Store them
      in state and optionally veto consensus on failure (advisory vs gating
      modes). *(Agent B)*
- [ ] **Restructure phase_progress.** The `"verify"` key is mixed in with
      alias keys (`agent_a`, `agent_b`), which is confusing.  Use a
      separate field or a dedicated verify-progress model. *(Agent B)*
- [ ] **Stabilize archiving.** Current UUID-per-step creates noisy,
      duplicate archive files.  Use a per-round or per-phase archive
      strategy. *(Agent B)*
- [ ] **Wire RETRY_PROMPT into phases.** The retry template exists in
      `extraction.py` but is not used.  Send a format-reminder follow-up
      when `<solution>` tags are missing, then re-extract. *(Agent A)*
- [ ] **Context management.** Summarization, diff-only views, and
      fresh-agent-per-round strategies for large tasks (proposal Section 8).
- [ ] **Token usage monitoring.** Log approximate token counts per
      follow-up and warn when approaching context limits.
- [ ] **Webhook support.** Replace polling with webhooks for agent status
      updates if the API supports them.

---

## Code quality

- [ ] **Remove dead code.** `extract_solution_and_analysis_from_latest` is
      a trivial alias; remove it. *(Agent A)*
- [ ] **Consolidate `_is_assistant_message`.** Both `api.py` and
      `extraction.py` have independent assistant-message detection.  Export
      a single canonical function. *(Agent A)*
- [ ] **Add request timeouts.** `api.py` has no per-request timeout;
      a hung connection blocks forever.  Add a default timeout and retry
      on `ConnectionError`. *(Agent B)*
- [ ] **Expand test coverage.** Add tests for: `step` CLI command, archive
      logic, `step_once` edge cases, real API message format extraction,
      and `wait_for_followup` resume behavior. *(Agent A: +17 tests)*
- [ ] Integration test harness that runs against the live API with a test
      repo.
- [ ] Cost tracking and per-run spend estimation.
- [ ] CI pipeline (GitHub Actions) for lint, typecheck, and unit tests.

---

## Documentation

- [ ] Update README "Current state" to reflect live API validation.
- [ ] Document Basic Auth, model availability, restart semantics, and
      verify-command behavior. *(Agent B)*
- [ ] Add a runbook / troubleshooting section for common failure modes.
