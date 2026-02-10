# Arena Run 2 Fixes

## Tier 1: Critical Bugs (correctness) -- DONE

All three critical bugs have been fixed in the codebase.

### 1. Fix `wait_for_followup` race condition -- DONE

**Problem:** `wait_for_followup` returned as soon as a new assistant message appeared, without requiring the agent to be `FINISHED`. Streaming responses could be truncated.

**Fix:** After detecting a new message, polls `api.status()` to confirm `FINISHED` before returning. If still `RUNNING`, continues polling. Applied to both `wait_for_followup` and `wait_for_all_followups`.

### 2. Always persist verdict text on CONTINUE -- DONE

**Problem:** The CONTINUE branch discarded the judge's reasoning.

**Fix:** Added `verdict_history: list[str]` field to `ArenaState` that accumulates every verdict text. `final_verdict` is also set on CONTINUE for immediate access.

### 3. Extract branch names from `status()` response -- DONE

**Problem:** `branch_names` was always empty because `launch()` doesn't return branch names.

**Fix:** After `wait_for_all_agents()` completes in `step_solve()`, fetches `status()` for each agent and reads `target.branchName`.

---

## Tier 2: Collaboration Quality -- PARTIALLY DONE

### 4. Improve verdict extraction reliability -- DONE

All three sub-items implemented:
- (a) `decision: CONSENSUS/CONTINUE` regex pattern as middle fallback.
- (b) Last occurrence wins when both keywords present.
- (c) `VERDICT_RETRY_PROMPT` re-prompts the judge for structured XML when keyword fallback is used.

### 5. File-committed outputs as source of truth -- TODO

**Problem:** Agents critique 10-15 line conversation summaries instead of actual branch deliverables (66-375 lines). This caused the weakest deliverable to be selected as winner.

**Design:** Agents commit structured outputs as files to predetermined paths on their branch. The orchestrator fetches these files by known path. Conversation extraction becomes a fallback only.

#### File naming convention

Pattern: `{round:02d}-{phase_number}-{phase_name}-{identity}-{artifact}.{ext}`

Phase numbers: solve=1, evaluate=2, revise=3.

Agent-committed files use alias as identity (e.g. `00-1-solve-agent_a-solution.md`). Orchestrator archive uses model nickname + content-hash uid (e.g. `00-1-solve-opus-solution-a1b2c3.md`).

Each agent commits its outputs to `arenas/NNNN/` in the target repo on its branch:

```
arenas/0003/
  00-1-solve-agent_a-solution.md
  00-1-solve-agent_a-analysis.md
  00-2-evaluate-agent_a-critique.md
  00-2-evaluate-agent_a-verdict.json
  00-3-revise-agent_a-solution.md
  00-3-revise-agent_a-analysis.md
```

#### Commit convention

Arena output files must be committed **separately** from any code or work artifacts, making them trivially droppable via `git rebase -i` after the run:

1. Commit arena files in a **dedicated commit**, separate from code changes.
2. Commit message: `[arena] round 00 solve agent_a` (prefix makes them greppable).
3. Only files under `arenas/NNNN/` in the commit. No code, no other files.
4. Commit code changes first, then the arena commit on top (arena commit is always the tip).

#### Fallback chain

1. **Re-prompt** the agent to commit the expected file.
2. **Conversation extraction** (XML tags for solution/analysis, JSON fenced block for verdict).

#### Implementation

- New module `arena/git.py`: `fetch_file_from_branch()` using `gh api` to fetch and base64-decode file content from a branch. Helper `parse_repo_owner_name()` to split repo URLs.
- Add `arena_number: int` to `ArenaConfig` so prompts can reference `arenas/NNNN/`.
- All prompts tell each agent its alias and exact filenames to commit.
- Phase functions fetch committed files from branches after agents finish, with re-prompt then conversation fallback.

### 6. Replace single-judge with multi-agent voting (collapsed into Evaluate) -- TODO

**Problem:** Single judge picks its own solution as the base (self-selection bias).

**Design:** Replace the 4-phase loop (Solve/Evaluate/Revise/Verify) with a 3-phase loop. The old Evaluate and Verify phases are collapsed into a single Evaluate phase that produces both critique and verdict. All agents vote -- no single judge.

#### 3-phase state machine

```
Solve -> Evaluate -> DONE (consensus)
                  -> Revise -> Evaluate -> DONE (consensus)
                                        -> Revise -> Evaluate -> ...
                                                              -> DONE (max rounds)
```

Consensus can be detected immediately after the first Evaluate (before any revision), saving a full round-trip when agents agree out of the gate.

#### Phase summary

- **Solve** (phase 1): Each agent independently works on the task, committing code/artifacts plus a solution summary and risk analysis.
- **Evaluate** (phase 2): Each agent reads all solutions (fetched from branches), writes a critique of each, AND votes for the best solution(s) excluding its own with a convergence score.
- **Revise** (phase 3): Each agent reads all critiques and produces a revised solution incorporating the strongest feedback.

#### Verdict format: JSON (not XML)

Each agent commits a `verdict.json` file, directly parseable with `json.loads()`:

```json
{
  "convergence_score": 9,
  "best_solutions": ["agent_b", "agent_c"],
  "remaining_disagreements": 0,
  "rationale": "All three solutions converged on layered backup with 3-2-1 rule..."
}
```

No XML parsing, no keyword fallback, no line-by-line string splitting.

#### Consensus aggregation

- `final_score = min(all agent scores)` -- deliberately conservative.
- `vote_tally = Counter(all best_solution votes across agents)`
- If `final_score >= 8` and one solution has N-1 votes: **CONSENSUS**, that solution wins.
- If `final_score >= 8` but votes split: **CONTINUE** (convergence without agreement on a winner).
- If `final_score < 8`: **CONTINUE**.
- If `round >= max_rounds`: **DONE** (no consensus).

#### State changes

**Remove** (hard breaking, no backward compatibility):
- `Phase.VERIFY` from the Phase enum
- `verify_judge`, `verify_prev_msg_count`, `judge_history`, `verify_progress`
- `paste_solutions` from ArenaConfig

**Add:**
- `verify_votes: dict[str, list[str]]` -- each agent's voted-for aliases
- `verify_scores: dict[str, int]` -- each agent's convergence score
- `verify_winner: str | None` -- the elected winner alias

#### Files affected

- `arena/state.py` -- Phase enum, ArenaConfig, ArenaState field changes
- `arena/extraction.py` -- Replace `Verdict`/`parse_verdict`/`_keyword_fallback` with `VoteVerdict`/`parse_vote_verdict_json`
- `arena/prompts.py` -- Rewrite all 3 templates; delete `verify_prompt` and `_branch_hint_block`
- `arena/phases.py` -- Rewrite `step_solve`, merge `step_evaluate` + `step_verify`, rewrite `step_revise`, delete `step_verify`
- `arena/orchestrator.py` -- Update `PHASE_HANDLERS`, `_archive_round`, `generate_final_report`
- `arena/__main__.py` -- Remove `--paste-solutions`, add `arena_number`, update status display

---

## Tier 3: Observability / UX -- DONE

All four items have been implemented in the codebase.

### 7. Include model names in log messages -- DONE

Added `agent_label(alias, state)` helper returning e.g. `"agent_a (opus)"`. Used throughout `phases.py`.

### 8. Switch state file to YAML -- DONE

`ruamel.yaml` added to dependencies. `save_state()` writes YAML by default. `load_state()` reads both YAML and legacy JSON.

### 9. Redesign archive naming -- DONE

New scheme: `{round:02d}-{phase_name}-{model}-{artifact_type}-{uid}.md`. Uses phase names and model names instead of misleading phase numbers and agent letters. Will be updated to include phase numbers (`{round:02d}-{phase_number}-{phase_name}-...`) as part of item #5.

### 10. Add per-agent timing and metadata capture -- DONE

Added `agent_timing` and `agent_metadata` fields to `ArenaState`. `_record_timing_start/_end` and `_capture_agent_metadata` helpers in `phases.py`. Status command displays timing and metadata.

---

## Execution Order

Items 1-4 and 7-10 are already implemented. The remaining work:

1. **`arena/git.py`** -- new module for fetching files from branches via `gh` CLI
2. **State changes** -- collapse to 3 phases, add voting fields, remove single-judge fields, add `arena_number`
3. **Extraction changes** -- `VoteVerdict` + `parse_vote_verdict_json`, remove old verdict code
4. **Prompt overhaul** -- all 3 phase templates with file paths, alias injection, commit convention
5. **Phase rewrites** -- file-based extraction, merged evaluate+verify, delete `step_verify`
6. **Orchestrator updates** -- 3-phase handlers, archive naming with phase numbers, vote breakdown in report
7. **CLI updates** -- remove `--paste-solutions`, add `arena_number`, vote display in status
8. **Test updates** -- across all test files
