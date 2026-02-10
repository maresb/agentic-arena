# Arena Run 2 Fixes

## Tier 1: Critical Bugs (correctness)

### 1. Fix `wait_for_followup` race condition

**Problem:** [api.py](arena/api.py) line 274 returns as soon as a new assistant message appears (`len(messages) > previous_msg_count`), without requiring the agent to be `FINISHED`. Streaming responses may be truncated, losing the `<verdict>` tag.

**Fix:** After detecting a new message, also poll `api.status()` to confirm the agent is `FINISHED` before returning. If the agent is still `RUNNING`, continue polling -- the message text may still be streaming.

```python
# In wait_for_followup(), after line 274:
if len(messages) > previous_msg_count and is_assistant_message(messages[-1]):
    # Ensure agent is actually finished (not still streaming)
    info = api.status(agent_id)
    if info["status"] == "FINISHED":
        return "FINISHED"
    # else: agent still running, message may be partial — keep polling
```

**File:** [arena/api.py](arena/api.py) ~line 274

### 2. Always persist verdict text on CONTINUE

**Problem:** [phases.py](arena/phases.py) line 430 `else` branch (CONTINUE) does not save `verdict_text`, discarding the judge's reasoning.

**Fix:** Set `state.final_verdict = verdict_text` in the CONTINUE branch as well. Rename the field or add a new `verdict_history` list to accumulate verdicts across rounds (since `final_verdict` is overwritten). At minimum, persist it immediately.

```python
# In step_verify(), the else branch at line 430:
else:
    state.final_verdict = verdict_text  # <-- ADD: persist even on CONTINUE
    state.round += 1
    ...
```

**Consideration:** Since CONTINUE means we loop back, the field gets overwritten next round. A better design is a `verdict_history: list[str]` field on `ArenaState` that appends each verdict. The `final_verdict` stays as-is for the terminal verdict. This requires a state schema change.

**Files:** [arena/phases.py](arena/phases.py) ~line 430, [arena/state.py](arena/state.py) (add `verdict_history` field)

### 3. Extract branch names from `status()` response

**Problem:** `branch_names` is always empty because the API `launch()` response doesn't include branch names. But `status()` returns `target.branchName`.

**Fix:** After `wait_for_agent` / `wait_for_all_agents` completes in `step_solve()`, fetch `api.status(agent_id)` and read `info["target"]["branchName"]`. Store in `state.branch_names[alias]`.

```python
# In step_solve(), after wait_for_all_agents() at ~line 135:
for alias, agent_id in pending.items():
    info = api.status(agent_id)
    branch = info.get("target", {}).get("branchName")
    if branch:
        state.branch_names[alias] = branch
_save()
```

**File:** [arena/phases.py](arena/phases.py) ~line 135

---

## Tier 2: Collaboration Quality

### 4. Improve verdict extraction reliability

**Problem:** Keyword fallback in [extraction.py](arena/extraction.py) line 121 is fragile -- scans for `\bCONSENSUS\b` anywhere, no priority logic, defaults to CONTINUE.

**Fix (multi-layered):**

- (a) Add a "decision: CONSENSUS/CONTINUE" regex pattern as a middle fallback between XML and bare keyword.
- (b) When keyword scan finds both `CONSENSUS` and `CONTINUE`, prefer the last occurrence.
- (c) Add a verdict re-prompt: when `parse_verdict` returns a keyword-fallback result, send a follow-up asking the judge to re-emit the `<verdict>` block.

**Files:** [arena/extraction.py](arena/extraction.py), [arena/phases.py](arena/phases.py) (for re-prompt logic)

### 5. Use branch files as source of truth for critique

**Problem:** Agents critique 10-15 line conversation summaries instead of the actual branch deliverables (66-375 lines). This caused the weakest deliverable to be selected as winner.

**Design:** After each solve/revise phase, if `state.branch_names` is populated:

1. Use `git ls-remote` or `gh api` to fetch the branch's file tree.
2. Fetch the target deliverable file(s) content (e.g., `recommendations.md`).
3. Use branch file content as the `solutions` passed into evaluate/verify prompts.
4. Fall back to conversation extraction if no branch changes detected.

This is the largest change. It requires:

- A new utility function to fetch file content from a remote branch (via GitHub API / `gh` CLI).
- A config field for the target deliverable filename(s).
- Changes to [phases.py](arena/phases.py) `step_evaluate()` and `step_verify()` to prefer branch content.
- Changes to [prompts.py](arena/prompts.py) to format branch-sourced content.

**Files:** [arena/api.py](arena/api.py) or new `arena/git.py`, [arena/phases.py](arena/phases.py), [arena/prompts.py](arena/prompts.py), [arena/state.py](arena/state.py)

### 6. Replace single-judge with multi-agent voting

**Problem:** Single judge picks its own solution as the base (self-selection bias). The judge consistently selects its own solution, regardless of quality.

**Design:** Replace the rotating-judge model with an all-agents-vote protocol:

1. **All agents receive the verify prompt** (not just one judge). Each agent sees all revised solutions and analyses, same as today.

2. **Each agent votes for the best solution, excluding its own.** An agent may vote for *multiple* others if it considers them effectively tied — this avoids forcing artificial distinctions between near-equivalent solutions.

3. **Each agent independently provides a convergence score** (1–10, same scale as today).

4. **The final consensus score is the minimum of all individual scores.** This is deliberately conservative: a single dissenting agent who sees substantive disagreements keeps the arena iterating. No optimistic outlier can drag up the aggregate.

5. **Winner selection requires N-1 votes.** If the final consensus score reaches the threshold (>= 8) and exactly one solution received a vote from every non-author agent (i.e. all N-1 other agents voted for it), that solution is selected as the base. If votes are split (no solution has N-1), the verdict is CONTINUE even if the score threshold is met — convergence without agreement on a winner means the agents still need to reconcile.

**Verdict extraction changes:**

The `<verdict>` XML block per agent becomes:

```xml
<verdict>
convergence_score: [1-10]
best_solutions: [comma-separated aliases, excluding own, at least one required]
remaining_disagreements: [count]
rationale: [why these solutions are best / what still differs]
</verdict>
```

The orchestrator then aggregates:
- `final_score = min(agent_scores)`
- `vote_tally = Counter(all best_solution votes across agents)`
- If `final_score >= 8` and `vote_tally[winner] == N-1`: CONSENSUS, select winner
- If `final_score >= 8` but votes are split: CONTINUE (score met but no agreement on winner)
- If `final_score < 8`: CONTINUE

**State changes:**

The current scalar `verify_judge` / `verify_prev_msg_count` fields become per-agent dicts. New fields needed:

- `verify_votes: dict[str, list[str]]` — each agent's list of voted-for aliases
- `verify_scores: dict[str, int]` — each agent's individual convergence score
- `verify_winner: str | None` — the elected winner alias (if any)

The existing `verify_judge` and `judge_history` fields become unused and can be removed.

**Files:** [arena/phases.py](arena/phases.py) `step_verify()`, [arena/prompts.py](arena/prompts.py) `verify_prompt()`, [arena/extraction.py](arena/extraction.py) (per-agent verdict parsing), [arena/state.py](arena/state.py) (verify state fields)

---

## Tier 3: Observability / UX

### 7. Include model names in log messages

**Problem:** Logs say "Agent agent_a finished" without the model name.

**Fix:** Audit all `logger.info/warning` calls that reference aliases and append the model name. Create a helper: `def agent_label(alias, state) -> str` that returns e.g. `"agent_a (opus)"`.

**Files:** [arena/phases.py](arena/phases.py), [arena/api.py](arena/api.py)

### 8. Switch state file to YAML

**Problem:** JSON is hard to read during manual step-by-step runs.

**Fix:** Replace `json.dump`/`json.load` in [state.py](arena/state.py) `save_state()`/`load_state()` with `ruamel.yaml`. Keep `.json` backward-compatible loading. New saves write `state.yaml`.

**Dependency:** Add `ruamel.yaml` to [pixi.toml](pixi.toml).

**Files:** [arena/state.py](arena/state.py), [pixi.toml](pixi.toml)

### 9. Redesign archive naming

**Problem:** Both `solve` and `analysis` get phase number `01` (misleading). Agent letters (`a`, `b`, `c`) are less readable than model names.

**Current:** `{round:02d}-{phase:02d}-{type}-{letter}-{model}-{uid}.md`

**Proposed:** Drop the phase number entirely; use phase name for sorting (solve < evaluate < revise < verify alphabetically is wrong, so use a padded prefix): `{round:02d}-{phase_name}-{model}-{artifact_type}-{uid}.md`

Or simpler: just replace phase numbers with names: `00-solve-opus-solution-a1b2c3.md`, `00-solve-opus-analysis-a1b2c3.md`, `00-evaluate-gpt-critique-d4e5f6.md`.

**File:** [arena/orchestrator.py](arena/orchestrator.py) `_archive_round()`

### 10. Add per-agent timing and metadata capture

**Problem:** No per-agent timing in status output; useful metadata (`summary`, `linesAdded`, `filesChanged`) from the API is discarded.

**Fix:**

- Add `agent_timing: dict[str, dict[str, float]]` to `ArenaState` (start/end per phase).
- After each `wait_for_agent`/`wait_for_followup`, record `time.time()`.
- Capture `linesAdded`, `filesChanged`, `summary` from `api.status()` response into a new `agent_metadata` field.
- Show timing in `status` command output.

**Files:** [arena/state.py](arena/state.py), [arena/phases.py](arena/phases.py), [arena/__main__.py](arena/__main__.py) `status` command

---

## Execution Order

The items have natural dependencies:

1. **Bug fix 1** (wait_for_followup race) -- standalone, test immediately
2. **Bug fix 2** (persist verdict on CONTINUE) -- standalone, small
3. **Bug fix 3** (branch names from status) -- standalone, small
4. **Verdict extraction** (#4) -- builds on fix 1
5. **Log model names** (#7) -- standalone, small
6. **Per-agent timing** (#10) -- standalone, medium
7. **Archive naming** (#9) -- standalone, small
8. **YAML state** (#8) -- standalone, medium, new dependency
9. **Branch files as critique source** (#5) -- builds on fix 3, largest change
10. **Multi-agent voting** (#6) -- builds on #5, largest redesign
