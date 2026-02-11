# Arena Run Summary 3: Local Vision Model Selection for Desktop Screenshot Classification

**Date:** 2026-02-10
**Task:** Select a local vision model (running on Ollama) for desktop screenshot classification on NVIDIA RTX PRO 6000 Blackwell 96GB
**Repo:** maresb/cursor-agentic-arena
**Agents:** Opus (agent_a), GPT (agent_b), Gemini (agent_c)
**Rounds:** max 3
**Arena dir:** arenas/0004
**State file:** arenas/0004/state.yaml

---

## Pre-flight Checks

- State file confirmed at `arenas/0004/state.yaml`
- Phase: `solve`, Round: 0, all agents at `pending`
- Alias mapping: agent_a=opus, agent_b=gpt, agent_c=gemini
- Model mapping:
  - opus → `claude-4.6-opus-high-thinking`
  - gpt → `gpt-5.2-codex-high-fast`
  - gemini → `gemini-3-pro`
- No verify commands (research/analysis task, not code)
- Arena number: 4
- Improvements from execution-plan2.md applied:
  - Tier 1 (critical bugs): all 3 DONE
  - Tier 2 (collaboration quality): verdict extraction DONE, file-committed outputs and multi-agent voting implemented
  - Tier 3 (observability): all 4 DONE

---

## Phase Log

### Phase 1: Solve (Round 0)

**Start time:** 22:21:52 UTC
**End time:** 22:38:46 UTC
**Wall time:** ~17 min (1014s)
**Outcome:** All 3 agents produced solutions on their branches. File-based
extraction failed for all 3 due to a bug in `git.py`; fell back to
conversation extraction. Content was later re-extracted from branches after
the bug was fixed.

| Agent | Model | Solve time | Branch | Lines added | Key recommendation |
|-------|-------|-----------|--------|-------------|-------------------|
| agent_a | opus | 824s (~14 min) | `cursor/desktop-vision-model-9dad` | 751 | Qwen2.5-VL-72B-Instruct, three-phase window-aware cropping |
| agent_b | gpt | 866s (~14 min) | `cursor/screen-content-description-model-7ef0` | 135 | Qwen2.5-VL-72B, two-pass tiling (global + high-res tiles) |
| agent_c | gemini | 1000s (~17 min) | `cursor/desktop-screenshot-model-preparation-b9f0` | 96 | Qwen2.5-VL-72B-Instruct, Naive Dynamic Resolution, no manual chunking for 4K |

**Notable:** All three agents independently recommended the same model
(Qwen2.5-VL-72B-Instruct). The main divergence is on chunking strategy:
opus proposes 3-phase window-aware cropping, gpt proposes two-pass tiling,
and gemini argues no manual chunking is needed for 4K.

#### Bugs discovered during Solve

**Bug 1 (critical): `gh api -f` uses POST instead of GET**

Root cause: `arena/git.py` line 89 used `["gh", "api", api_path, "-f", f"ref={branch}"]`.
The `-f` flag in `gh api` implicitly changes the HTTP method from GET to POST.
The GitHub Contents API requires GET. This caused every branch file fetch to
return 404, even though the files were correctly committed by all agents.

Fix: Added `-X GET` to force the correct HTTP method. Committed as `b36da4b`.

Reproduction:
```
# Fails (POST):
gh api /repos/owner/repo/contents/path -f ref=branch  # 404
# Works (explicit GET):
gh api -X GET /repos/owner/repo/contents/path -f ref=branch  # 200
# Also works (query param):
gh api "/repos/owner/repo/contents/path?ref=branch"  # 200
```

**Bug 2 (critical): Re-prompt corrupts conversation extraction**

When file fetch fails, `_fetch_with_retry()` re-prompts the agent to commit
the file. If the agent had already committed it (which all three did), the
agent replies with a meta-response like "I already committed the file." The
conversation fallback then picks up this meta-response as the "latest
response," discarding the actual work product.

Impact for this run:
- **agent_a (opus):** Re-prompt caused opus to re-generate its full solution
  in chat (5+ min extra). Conversation extraction got 18,674 chars — close
  to the branch version (18,649). Lucky outcome, but very wasteful.
- **agent_b (gpt):** Re-prompt response was 542 chars ("I already committed
  the file"). The actual 7,791-char solution was lost from extraction.
  **Complete data loss.**
- **agent_c (gemini):** Similar pattern. Branch has 5,197 chars; conversation
  extraction got 5,200 chars (close match — gemini likely repeated content).

Resolution: Re-extracted all solutions/analyses from branches after fixing
the git.py bug. GPT's solution went from 542 → 7,791 chars.

**Missing feature: Full conversation capture — FIXED**

The orchestrator calls `api.get_conversation()` multiple times but never
persisted the full conversation transcript to disk. Once the process exits,
the conversation data was gone.

Fix: Added `_save_conversation()` to `phases.py` that writes the full
conversation to `conversations/{model}.json` under the arena directory
after each phase. Committed as `a5b5379` and `cc5264a`.

**Bug 3: Integration tests launched real agents**

`tests/test_integration.py` had a `test_launch_and_stop_agent` test guarded
only by `CURSOR_API_KEY` being set. Since `.env` is loaded in the dev
environment, every `pixi run pytest` launched a real agent. Found 8
spurious "Hello message output" agents on the account.

Fix: Changed guard to require `RUN_INTEGRATION_TESTS=1` (committed as
`fea388b`). Removed the launch test entirely (committed as `ba3d330`).

**Bug 4 (design): Conversation text used as solution fallback**

The old code fell back to XML extraction from the chat log when branch
files weren't found. The prompts never asked agents to use XML tags,
so this path always failed and either used the full chat response or
re-prompted for XML formatting (wasting another round-trip).

Fix: Removed the entire XML/conversation fallback path. Agents must
commit files. `_fetch_with_retry` now retries up to 3 times. Dead code
removed: `extract_xml_section`, `extract_solution_and_analysis`,
`RETRY_PROMPT`, `_extract_with_retry`. Committed as `7a06be2`.

**Intermission: Privacy Mode (Legacy) outage**

Between the solve and evaluate phases, the Cursor API began returning
400 errors: "Background agent is not supported in Privacy Mode (Legacy)."
All agent endpoints (status, list, conversation) became inaccessible.
Resolved by switching the account from Privacy Mode (Legacy) to Privacy
Mode in Cursor settings. Agents and conversations survived the outage.

#### Commits during Solve phase

| Commit | Description |
|--------|-------------|
| `b36da4b` | Fix `gh api` POST→GET bug in `git.py` |
| `a5b5379` | Save full conversation transcripts to `conversations/` |
| `cc5264a` | Name conversation files by model instead of alias |
| `fea388b` | Require `RUN_INTEGRATION_TESTS=1` for live API tests |
| `ba3d330` | Remove live agent launch test |
| `7a06be2` | Remove XML fallback; require committed files for all content |

---

### Phase 2: Evaluate (Round 0)

**Outcome:** All 3 agents committed critique and verdict files. No consensus
reached (final_score=6, winner=None). Transitioning to revise.

| Agent | Model | Eval time | Critique size | Score | Voted for |
|-------|-------|-----------|---------------|-------|-----------|
| agent_a | opus | 208s | 12,051 chars | 8 | agent_b |
| agent_b | gpt | 208s | 3,313 chars | 6 | agent_a |
| agent_c | gemini | 208s | 3,845 chars | 8 | Agent A* |

*\*Gemini wrote "Agent A" instead of "agent_a" — see Bug 5 below.*

**Vote tally (before normalization):** agent_b: 1, agent_a: 1, Agent A: 1
**Vote tally (after normalization):** agent_a: 2, agent_b: 1
**Final score:** 6 (min of 8, 6, 8) — below consensus threshold of 8
**Winner:** None (agent_a has 2 votes = N-1, but final_score < 8)

#### Bugs discovered during Evaluate

**Bug 5 (design): Evaluate/Revise pastes content instead of branch refs**

The `evaluate_prompt()` and `revise_prompt()` were building the full
solution/critique text into the follow-up message. This defeats the purpose
of having agents commit files to branches — the whole point is that agents
read each other's work via `git show`, keeping prompts small and making
agents work with the actual committed deliverables.

Fix: Rewrote both prompts to provide branch names and file paths, telling
agents to use `git show origin/{branch}:{path}` to read each other's work.
Committed as `9d30f42`.

**Bug 6: Vote alias format not normalized**

Gemini voted for `"Agent A"` (human label) instead of `"agent_a"` (alias
format). The vote tally treated these as different candidates, so agent_a
only got 1 vote instead of 2.

Fix: Added `_normalize_alias()` to lowercase and replace spaces with
underscores. `parse_vote_verdict_json()` now accepts an optional
`valid_aliases` parameter to filter unknown targets. Committed as `651414e`.

#### Commits during Evaluate phase

| Commit | Description |
|--------|-------------|
| `9d30f42` | Pass branch file references in evaluate/revise instead of pasting content |
| `651414e` | Normalize vote aliases (Agent A → agent_a) in verdict parsing |

---

### Phase 3: Revise (Round 0)

**Outcome:** All 3 agents committed revised solutions and analyses.
Clear convergence visible — all agents adopted window-aware cropping from
agent_a's original proposal.

| Agent | Model | Revise time | Solution size | Analysis size | Key changes |
|-------|-------|-------------|---------------|---------------|-------------|
| agent_a | opus | 250s (~4 min) | 15,325 chars | 9,339 chars | Updated .gitignore, added critique/verdict files |
| agent_b | gpt | 249s (~4 min) | 7,279 chars | 1,650 chars | Adopted window-aware cropping, fallback to grid tiling |
| agent_c | gemini | 249s (~4 min) | 3,973 chars | 2,092 chars | Shifted from Q8_0 → Q4_K_M quantization, adopted window-aware cropping |

**Convergence signals:**
- All three now recommend window-aware cropping using GNOME metadata
- All agree on Qwen2.5-VL-72B-Instruct
- Gemini adopted structured JSON output schema from GPT
- Remaining disagreements: quantization (Q8_0 vs Q4_K_M), whether
  chunking is needed for 4K

No bugs discovered during the revise phase. The branch-reference approach
worked correctly — agents read each other's critiques via `git show`.

---

### Phase 4: Evaluate (Round 1)

**Outcome:** Scores improving. agent_a (opus) is the consensus winner
(2/2 non-self votes), but GPT's convergence score of 7 keeps the minimum
below the consensus threshold of 8. Transitioning to revise round 1.

| Agent | Model | Score | Voted for |
|-------|-------|-------|-----------|
| agent_a | opus | 9 | agent_b |
| agent_b | gpt | 7 | agent_a |
| agent_c | gemini | 9 | agent_a |

**Vote tally:** agent_a: 2, agent_b: 1
**Final score:** 7 (min of 9, 7, 9) — below consensus threshold of 8
**Winner:** agent_a (2 votes = N-1, but final_score < 8)

Alias normalization fix confirmed working — both gemini and gpt voted
for `agent_a` and the tally correctly shows 2 votes.

---

### Phase 5: Revise (Round 1)

**Outcome:** All 3 agents committed revised solutions. Agents are
tightening their outputs (opus went from 15K to 9K chars for solution).

| Agent | Model | Revise time | Solution size | Analysis size |
|-------|-------|-------------|---------------|---------------|
| agent_a | opus | ~142s | 8,766 chars | 2,661 chars |
| agent_b | gpt | ~188s | 5,626 chars | 1,509 chars |
| agent_c | gemini | ~101s | 3,426 chars | 1,868 chars |

---

### Phase 6: Evaluate (Round 2)

**Outcome:** Opus and Gemini score 10 (perfect), GPT still at 7.
agent_a (opus) is unanimous winner (2/2 non-self votes) but GPT's
score prevents consensus.

| Agent | Model | Score | Voted for |
|-------|-------|-------|-----------|
| agent_a | opus | 10 | agent_b |
| agent_b | gpt | 7 | agent_a |
| agent_c | gemini | 10 | agent_a |

**Vote tally:** agent_a: 2, agent_b: 1, agent_c: 1
**Final score:** 7 (min of 10, 7, 10) — below consensus threshold of 8

**Note:** GPT didn't commit its critique file initially and required a
re-prompt (retry 1/3 succeeded). The file retry mechanism worked correctly.

**Observation:** GPT consistently scores 7 across rounds while opus and
gemini converge to 9→10. This may indicate GPT has a stricter convergence
bar, or the scoring rubric instruction ("Score 8+ only if all remaining
differences are trivial") is being interpreted more strictly by GPT.

---

#### Design improvement between Evaluate R2 and Revise R2

**Bug 7 (design): Agents recreate files from scratch each round**

`expected_path` encoded round and phase into every filename (e.g.
`00-1-solve-agent_a-solution.md`, `01-3-revise-agent_a-solution.md`).
Each round created new files, so agents wrote from scratch instead of
refining. Git diffs between rounds were invisible.

Fix: Simplified `expected_path` to produce stable per-agent paths
(e.g. `agent_a-solution.md`). Agents now overwrite the same file each
round, producing meaningful git diffs. The orchestrator's archival
copies (with round/phase/model/UID naming) are unchanged.

Committed as `e9af5ac`.

---

### Phase 7: Revise (Round 2)

**Outcome:** All 3 agents committed revised solutions using the new
stable file paths (`agent_a-solution.md` instead of
`02-3-revise-agent_a-solution.md`). This is the last revise round.

| Agent | Model | Revise time | Solution size | Analysis size |
|-------|-------|-------------|---------------|---------------|
| agent_a | opus | ~182s | 9,528 chars | 2,673 chars |
| agent_b | gpt | ~182s | 4,999 chars | 1,169 chars |
| agent_c | gemini | ~139s | 3,647 chars | 1,811 chars |

**Stable paths confirmed working:** Agents committed to the new
round-agnostic file paths on their first attempt. No retries needed.

---

### Phase 8: Evaluate (Round 3 — Final)

**Outcome: CONSENSUS REACHED.** GPT finally scored 8 (up from 7),
bringing the minimum score to the threshold. agent_a (opus) wins
unanimously.

| Agent | Model | Score | Voted for |
|-------|-------|-------|-----------|
| agent_a | opus | 10 | agent_b, agent_c |
| agent_b | gpt | 8 | agent_a |
| agent_c | gemini | 10 | agent_a |

**Vote tally:** agent_a: 2, agent_b: 1, agent_c: 1
**Final score:** 8 (min of 10, 8, 10) — meets consensus threshold
**Winner:** agent_a (opus)
**Consensus:** Yes
**Report:** `arenas/0004/report.md`
**PR link:** https://github.com/maresb/cursor-agentic-arena/compare/main...cursor/desktop-vision-model-9dad?expand=1

---

## Summary

### Arena outcome

All three agents unanimously recommended **Qwen2.5-VL-72B-Instruct** with
**Q4_K_M** quantization and **window-aware cropping** using GNOME metadata.
The solution converged fully — no remaining disagreements.

The arena ran for 3 rounds (solve + 3x evaluate-revise cycles). Consensus
was blocked for 2 rounds by GPT scoring 7 while opus and gemini scored
9–10. GPT finally raised its score to 8 in the final round.

### Timing

| Phase | Wall time |
|-------|-----------|
| Solve (R0) | ~17 min |
| Evaluate (R0) | ~3.5 min |
| Revise (R0) | ~4 min |
| Evaluate (R1) | ~3.5 min |
| Revise (R1) | ~3 min |
| Evaluate (R2) | ~4 min |
| Revise (R2) | ~3 min |
| Evaluate (R3, final) | ~2.5 min |
| **Total** | **~40 min** |

### Bugs and improvements (7 total)

| # | Severity | Description | Commit |
|---|----------|-------------|--------|
| 1 | Critical | `gh api -f` sends POST instead of GET | `b36da4b` |
| 2 | Critical | Re-prompt corrupts conversation extraction | (removed fallback) |
| 3 | Medium | Integration tests launched real agents | `fea388b`, `ba3d330` |
| 4 | Design | Conversation text used as solution fallback | `7a06be2` |
| 5 | Design | Evaluate/Revise pastes content instead of branch refs | `9d30f42` |
| 6 | Medium | Vote alias format not normalized | `651414e` |
| 7 | Design | Agents recreate files from scratch each round | `e9af5ac` |

### New features added

- Automatic conversation transcript capture (`conversations/{model}.json`)
- Branch file references in evaluate/revise prompts (agents read via `git show`)
- Vote alias normalization (Agent A → agent_a)
- Stable file paths (agents edit same file across rounds)

### Recommendations for future runs

1. **GPT's strict scoring:** GPT consistently scored 7 while others scored
   9–10. Consider whether the scoring rubric needs adjustment, or accept
   that GPT has a higher bar for "trivial differences."
2. **Opus verbosity:** Opus consistently produces 2–3x more content than
   the other agents. This isn't necessarily bad but may inflate token costs.
3. **Missing feature: `git fetch` before `git show`:** Agents need the
   remote branches to be available locally. Should verify that
   `git fetch origin` runs before `git show origin/{branch}:path`.
4. **Missing feature: Round-over-round diffs:** Now that agents use stable
   paths, the orchestrator could log `git diff` between rounds to show
   exactly what changed in each revision.
5. **Missing feature: Per-agent token costs:** Token usage is tracked but
   not surfaced in the report or summary.

---

## Post-run Design Review

After the arena completed, a review of the outputs identified three
design improvements worth implementing.

### Design issue 8: report.md is a flat dump, not a useful deliverable

`generate_final_report` concatenates ALL agents' solutions and analyses
into a 651-line `report.md` with no structure. The winning solution has
no prominence. The user has to scroll through three agents' outputs to
find what matters.

**Decision:** Split into two files:
- `report.md` — rolling per-round summary (updated after every phase).
  Compact metadata (scores, votes, consensus status) with hyperlinks
  to the archived files. No inlined solution text.
- `winning-solution.md` — just the winner's final solution + analysis.
  The clean deliverable.

**Implementation (commits `5ea1dfe`, `e3d7bb7`, `f51ee20`):**
- Added `update_report()` in `arena/orchestrator.py`: generates a compact
  `report.md` with header metadata, agents table, per-round verdict
  sections (scores, votes, divergences), and hyperlinks to archived files
  using content-hashed `_archive_filename()`. Solution text is never
  inlined.
- Added `_write_winning_solution()`: creates `winning-solution.md` with
  just the winning agent's solution + analysis and a PR link.
- `step_once` now calls `update_report` after every phase and
  `_write_winning_solution` on completion.
- `generate_final_report` retained as a legacy wrapper calling both.
- 13 new tests across `TestUpdateReport` and `TestWriteWinningSolution`.

### Design issue 8b: Verdict disagreements are vague counts, not structured

The `VoteVerdict` model had a `remaining_disagreements` integer field.
This gave no actionable information about what agents disagree on. The
consensus threshold of 8 was too low — GPT scored 8 even with real
disagreements.

**Decision:** Replace `remaining_disagreements` with a structured
`divergences` list of `{topic, description}` objects. Enforce
bidirectional constraints: empty divergences → score must be 10; non-empty
divergences → score capped at 9. Raise consensus threshold to 9.

**Implementation (commits `f322b7b` through `7aa02c3`):**
- Added `Divergence(BaseModel)` with `topic` and `description` fields
  in `arena/extraction.py`.
- Updated `VoteVerdict` to use `divergences: list[Divergence]` instead of
  `remaining_disagreements`.
- Added `_enforce_divergence_score()` for bidirectional score enforcement.
- Added `verify_divergences` field to `ArenaState`.
- Wired divergences through `step_evaluate` and verdict archival.
- Raised consensus threshold from 8 to 9.
- Updated `EVALUATE_TEMPLATE` with divergences schema and scoring rules.
- 6 new tests in `TestDivergenceScoreEnforcement`, plus updates to
  existing verdict/phase/prompt tests.

### Design issue 9: Three-phase model (solve/evaluate/revise) is confusing

The current model has three phases but only two operations. "Solve" and
"revise" both produce a solution + analysis — the only difference is
whether there are prior critiques. This creates confusing archive naming:
round 03's last file is `03-3-revise` but evaluate actually ran after
revise. Round 0 has three phases while subsequent rounds have two.

**Decision:** Simplify to two phases — **generate** and **evaluate**:
- Generate round 0 = launch agents (what "solve" does today)
- Generate round N = send followup with critiques (what "revise" does)
- Each round is a clean pair: generate → evaluate
- Archive files: `00-1-generate-opus-solution-uid.md`,
  `00-2-evaluate-opus-critique-uid.md`

**Implementation (commit `a7d30f8`):**
- `Phase` enum changed from `SOLVE/EVALUATE/REVISE/DONE` to
  `GENERATE/EVALUATE/DONE`.
- `PHASE_NUMBERS` updated to `{"generate": 1, "evaluate": 2}`.
- `_LEGACY_PHASE_MAP` added to `load_state` for backward compatibility
  (maps `"solve"` and `"revise"` → `"generate"`).
- `step_solve` + `step_revise` merged into `step_generate` in
  `arena/phases.py`. Round 0 launches agents; round > 0 sends followup
  with critique branch references.
- `solve_prompt` + `revise_prompt` merged into `generate_prompt` in
  `arena/prompts.py`. Conditionally includes critique references when
  `agent_critique_files` is provided.
- `PHASE_HANDLERS` simplified to `{GENERATE: step_generate, EVALUATE:
  step_evaluate}`.
- `_archive_round` simplified — always uses `"generate"` for solution
  archives (no more `sol_phase` branching).
- `step_evaluate` now transitions directly to `GENERATE` (incrementing
  the round and clearing transient state) instead of `REVISE`.
- All test classes updated: `TestStepSolve` → `TestStepGenerateInitial`,
  `TestStepRevise` → `TestStepGenerateRevision`, etc.

### Design issue 10: No way to inject operator comments mid-run

The orchestrator is the sole communicator with agents. There's no way
for the operator to provide additional context, course corrections, or
clarifications during a run.

**Decision:** Add `pixi run arena add-comment --arena-dir arenas/NNNN`:
- Interactive CLI that checks agent status
- If agents are idle (between steps): send immediately via `followup`
- If a step is in progress: queue to sidecar file
  (`pending-comments.json`), delivered at next phase boundary
- Options: wrap in "operator context" framing, target specific agents
- The Cursor API only supports immediate delivery (`followup`), so
  queuing is implemented via sidecar file

**Implementation (commit `a7d30f8`):**
- Added `deliver_pending_comments()` in `arena/orchestrator.py`: reads
  `pending-comments.json`, sends each queued message to targets via
  `api.followup()`, waits for responses, saves conversations, deletes
  the sidecar.
- `step_once` calls `deliver_pending_comments` before every phase handler.
- Added `add-comment` subcommand in `arena/__main__.py`:
  - **Interactive mode** (no `--message` flag): walks through target
    selection, delivery mode (immediate/queue), message text, and
    wrap confirmation.
  - **Non-interactive mode**: `--message`/`-m`, `--queue`/`--immediate`,
    `--no-wrap`, `--targets` flags.
  - Detects in-progress steps (`phase_progress == "sent"`) and restricts
    to queued delivery.
  - Queued delivery appends to `pending-comments.json` (supports multiple
    queued comments before next phase).
- Sidecar format: JSON array of `{message, wrapped, targets, timestamp}`.
- `OPERATOR_WRAP_TEMPLATE` for consistent framing.
- 8 CLI tests + 7 orchestrator delivery tests.

### Commits for post-run design improvements

| Commit | Description |
|--------|-------------|
| `f322b7b` | Add Divergence model and bidirectional score enforcement |
| `b5eb324` | Add verify_divergences field to ArenaState |
| `b0f95e5` | Wire divergences through evaluate phase and verdict archival |
| `8b3932f` | Raise consensus threshold from 8 to 9 |
| `7aa02c3` | Update EVALUATE_TEMPLATE with divergences schema and scoring rules |
| `5ea1dfe` | Add rolling update_report() and _write_winning_solution() |
| `e3d7bb7` | Call update_report from step_once; remove redundant CLI report call |
| `f51ee20` | Update report tests for rolling report and winning solution |
| `a7d30f8` | Simplify to 2-phase model and add operator comment injection |
