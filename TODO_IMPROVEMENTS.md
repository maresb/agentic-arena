# Improvements Roadmap

This file tracks architectural, usability, and feature improvements identified from dogfooding sessions. It complements `TODO.md` which tracks immediate bugs and validations.

---

## 1. Artifact Naming & Organization

**Goal:** Make file artifacts sortable, descriptive, and easy to navigate without relying on opaque UUIDs.

- **Proposed Format:** `{round:02d}-{phase_number:02d}-{phase}-{model_letter}-{model}-{uid}.md`
  - `round`: 00, 01, ...
  - `phase_number`: 01 (solve), 02 (evaluate), 03 (revise), 04 (verify)
  - `model_letter`: a, b, c
  - `model`: opus, gpt, gemini
  - `uid`: short hex (kept for uniqueness, but at the end)

**Example:** `00-01-solve-a-opus-c25c32.md`

## 2. Merge Strategy

**Goal:** Make it easy for the user to apply the winner's code without dangerous auto-merging.

- **Mechanism:** In the final report (`report.md`) and the CLI output, print the full GitHub Pull Request URL (or branch comparison URL) for the winning agent's branch.
- **Action:** User clicks the link, reviews the diff in GitHub, and merges manually.
- **Constraint:** Do *not* implement auto-merging or local `git merge` in the orchestrator.

## 3. Polling Visibility

**Goal:** Reduce "is it hung?" anxiety during long-running agent phases.

- **Mechanism:** Print a single `.` character to stderr for every polling interval (e.g. every 10s).
- **Constraint:** Do not flood the terminal with newlines or verbose logs.

## 4. Verify Idempotency (Correctness)

**Goal:** Ensure that crashing during the verify phase doesn't lead to duplicate prompts or inconsistent verdicts on restart.

- **Problem:** Currently `step_verify` selects a judge, appends to history, and sends a follow-up. If it crashes before saving state, the next run selects a *new* judge (or appends again) and re-sends.
- **Fix:** Persist a "verify sent" marker, the selected judge ID, and the previous message count in `state.json`. On restart, check this marker to skip re-sending.

## 5. Context Management

**Goal:** Prevent token limit exhaustion in multi-round arenas.

- **Problem:** Full conversation history (including pasted solutions/critiques) is preserved. By round 3, context can exceed 100k+ tokens.
- **Strategy:**
  - **Summarization:** Use a cheap model to summarize previous rounds before pasting into the prompt.
  - **Diff-only views:** Instead of pasting full file contents, use `git diff` output where possible.
  - **Fresh agents:** Launch fresh agents for each round (solve/revise) instead of maintaining long-lived conversation threads, passing only the necessary context.
