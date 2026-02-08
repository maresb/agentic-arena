# Arena Run Summary 2: Home Assistant Backup Strategy

**Date:** 2026-02-08
**Task:** Evaluate HA backup methodology and recommend a path forward for add-on config dilemma
**Repo:** maresb/homeassistant-config
**Agents:** Gemini (agent_a), GPT (agent_b), Opus (agent_c)
**Rounds:** max 2 (only round 0 completed before stopping; round 1 started due to extraction bug)
**Arena dir:** arenas/0002
**Total wall time (round 0):** ~20 min (1221s)
**Outcome:** Arena declared CONTINUE due to extraction bug; actual verdict was CONSENSUS (score 9)

---

## Timeline

### Init

- Alias mapping: agent_a=gemini, agent_b=gpt, agent_c=opus
- Task: Review HA backup approach, research best practices, recommend strategy
  for add-on config backup dilemma
- No verify commands (this is a planning/research task, not code)
- Pre-flight fix: removed stale "temporarily unavailable" comment on the Gemini
  model entry in `prompts.py`

### Agent IDs

| Alias | Model | Agent ID |
|-------|-------|----------|
| agent_a | Gemini | `bc-beef6148-9586-40c2-ac1a-6078af79f903` |
| agent_b | GPT | `bc-bd14419c-86b6-4553-8e29-4b329555595f` |
| agent_c | Opus | `bc-bbce45c6-328c-41d4-b4c7-3c0dfda578ea` |

---

## Phase Log

### Step 1: Solve

**Wall time:** ~7 min (430s), bottlenecked by GPT (6.5 min)
**Outcome:** All 3 agents produced solutions and analyses. All committed
`recommendations.md` to their branches.

| Agent | Model | Finish time | Key position |
|-------|-------|-------------|-------------|
| agent_a | Gemini | ~2 min | Git = config history only; use Google Drive Backup add-on; **don't** put add-on configs in git |
| agent_b | GPT | ~6.5 min | Same as Gemini: built-in backups as truth, git for history, optional sanitized export |
| agent_c | Opus | ~3.5 min | Git is sound-but-incomplete; **`$SUPERVISOR_TOKEN` via shell_command** can dump redacted add-on configs to `/config/` |

**Key divergence:** Opus found a concrete technical path to solve the add-on
dilemma (Supervisor API token available inside HA container for
`shell_command`), while Gemini and GPT both say "don't bother, use full
backups." This is a substantive disagreement that should produce useful debate.

**All 3 agree on:** layered backup strategy, git for config versioning (not
full backup), automated off-site backups via HA's built-in system.

### Step 2: Evaluate

**Wall time:** ~4 min (248s), again bottlenecked by GPT (~4 min vs ~16-30s
for Opus and Gemini)

**Key debate lines:**

1. **Security vs. observability (main disagreement):**
   - Gemini + GPT: "Don't dump add-on configs to git -- secrets risk is too
     high, redaction is brittle."
   - Opus: "Redacted *structural* config is valuable. Secrets and structure
     are different things. You can redact passwords and still track 'Mosquitto
     is configured with these listeners.'"

2. **Concreteness:**
   - Opus criticizes both others for being too vague / high-level. "Strategy
     without implementation is a whiteboard exercise." Points out GPT's 4
     bullet points don't meet the "actionable next steps" bar.

3. **`.storage/` tracking:**
   - Opus: selective tracking of entity/device/area registries is high-value,
     low-secret, and painful to recreate.
   - GPT: "tracking `.storage/` is noisy, can include sensitive data, bad
     default."
   - Gemini: doesn't address it.

4. **Cross-pollination (agreements):**
   - All adopt Gemini's "Configuration History" rebranding idea.
   - GPT and Opus both like the phased rollout structure.
   - Gemini acknowledges Opus's `$SUPERVISOR_TOKEN` finding as technically
     correct but wants to label it "Possible but Discouraged."

**Critique quality:** High across all three. Opus's critique was the most
detailed and actionable (~70 lines). Gemini's was well-structured. GPT was
thorough but slower.

### Step 3: Revise

**Wall time:** ~8.5 min (512s). GPT took **8+ minutes** (vs ~40s for Gemini
and Opus). This is becoming a serious bottleneck.

**Convergence:**
- All three now agree on: repo = "Configuration History", layered backup
  strategy, built-in HA backups as Phase 1, 3-2-1 rule, multiple off-site
  options (not just Google Drive).
- Opus conceded: downgraded `$SUPERVISOR_TOKEN` approach to optional/advanced,
  removed `.storage/` tracking from default plan.
- Gemini conceded: acknowledged `$SUPERVISOR_TOKEN` feasibility, added as
  "possible but discouraged," improved actionability with phased plan.
- GPT: adopted phased rollout, explicit 3-2-1 framing, cautionary advanced
  export path with install-type caveats.

**Remaining disagreements (nuanced, not substantive):**
1. Opus vs. Gemini: whether to even document the add-on config export path
   (Opus: "yes, as optional/advanced"; Gemini: "mention but discourage").
2. Opus vs. GPT: `.storage/` tracking (Opus: "sometimes useful in private
   repos"; GPT: "never belongs in git").

These are framing/scope disagreements rather than technical ones.

### Step 4: Verify (Round 0)

**Wall time:** ~24s (fast -- only one agent responds)
**Judge:** agent_a (Gemini)
**Reported verdict:** CONTINUE (score=None -- keyword fallback)
**Actual verdict (fetched from API post-hoc):** CONSENSUS (score=9)

**What the judge actually said:**

The judge's full response was later fetched from the API. Gemini wrote a
thorough analysis with AGREEMENT POINTS, DISAGREEMENT POINTS, MOST SIGNIFICANT
DIFFERENCE, and a CONVERGENCE SCORE of 9. It then produced a properly-formed
`<verdict>` tag at the end with:
- `decision: CONSENSUS`
- `convergence_score: 9`
- `remaining_disagreements: 0`
- `base_solution: Agent A`
- `modifications:` (list of specific changes from B and C to incorporate)

The modifications requested:
1. Add explicit "3-2-1 Backup Rule" framing from Agent B/C
2. Broaden Phase 1 to list Samba Backup and Nextcloud alongside Google Drive
3. Reference the `$SUPERVISOR_TOKEN` mechanism from Agent C for technical
   due diligence, while maintaining the recommendation against implementing it

**Why it was misclassified:**

Root cause: **race condition in `wait_for_followup`** (api.py line 274). The
function returns as soon as a new assistant message appears in the conversation
(`len(messages) > previous_msg_count and is_assistant_message(messages[-1])`),
without checking that the agent status is FINISHED. If the API streams the
response incrementally, the `text` field may be truncated when first detected.
The truncated text was missing the `<verdict>` block and the word "CONSENSUS"
(both appear at the very end of the response). The keyword scanner defaulted
to CONTINUE (default when neither keyword is found).

**Consequence:** Round 1 started unnecessarily. The arena should have declared
consensus after round 0.

### Step 5+: Round 1 (not completed)

Round 1 evaluate phase was pending when we stopped to investigate the
extraction bug. No further steps were run.

---

## Branch Inspection

Three branches on `maresb/homeassistant-config`:

| Branch | Agent | Model | Lines | Commits |
|--------|-------|-------|-------|---------|
| `cursor/ha-backup-recommendations-455b` | agent_a | Gemini | 66 | 2 content commits |
| `cursor/ha-backup-recommendations-df39` | agent_b | GPT | 122 | 2 content commits |
| `cursor/home-assistant-backup-strategy-d842` | agent_c | Opus | 375 | 3 content commits |

**Note:** Branch-to-agent mapping was inferred by content matching, not from
the API. The `branch_names` field in state.json is empty because the API
launch response doesn't return branch names. This is a critical missing
feature.

**Winner on the merits: Opus (agent_c)** -- by far the most comprehensive
and actionable deliverable. Includes:
- Full gap analysis table of current approach
- Layered backup strategy with 3-2-1 mapping
- Comparison of 4+ community backup tools
- Working Python script for add-on config dump with security caveats
- 4-phase action plan with code examples (cron, YAML automations)
- Summary table mapping concerns → recommendations
- Restore guide outline

**The arena's own consensus process selected Gemini as the winner.** This is
a significant failure mode: the consensus loop evaluated 10-15 line
conversation summaries and missed that Opus produced the clearly superior
375-line deliverable.

---

## Issues & Rough Edges

### Critical Bugs

1. **Race condition in `wait_for_followup` causes incorrect verdict.**
   (api.py line 274). The function returns as soon as a new assistant message
   appears, without requiring the agent to be FINISHED. Streaming responses
   may be truncated, losing the `<verdict>` tag and CONSENSUS keyword. This
   caused round 0's CONSENSUS verdict to be misclassified as CONTINUE,
   wasting an entire round. **Fix:** also require agent status == FINISHED
   before returning.

2. **Verdict text not persisted on CONTINUE.** When the judge says CONTINUE,
   `state.final_verdict` is not set (phases.py line 431 else branch). The
   judge's full reasoning is discarded, making post-hoc analysis impossible.
   We only discovered the correct verdict by manually fetching the
   conversation from the API. **Fix:** always persist `verdict_text`
   regardless of the decision.

3. **Keyword fallback is fragile.** The fallback scans for `\bCONSENSUS\b`
   anywhere in the text. If found → CONSENSUS; otherwise → default CONTINUE.
   Multiple failure modes: (a) truncated text missing the keyword entirely,
   (b) keyword appearing in prose discussion rather than the actual decision,
   (c) both keywords present in the same text. **Fix:** prefer the `<verdict>`
   tag approach and add a re-prompt specifically for verdict formatting; make
   the keyword fallback smarter (e.g., weight last occurrence, look for
   "decision: X" patterns).

### API / Integration Gaps

4. **`branch_names` not returned by API.** The `branch_names` dict in
   state.json is always empty because the API launch response doesn't include
   branch name info. This makes `--branch-only` mode non-functional and
   prevents the orchestrator from knowing which branch belongs to which agent.
   We had to infer the mapping from branch content. **Must fix for
   branch-aware features to work.**

5. **`token_usage` always empty.** Conversation messages don't include `usage`
   metadata, so the token tracking feature is entirely inert. Cost estimates
   in the report will always be blank.

6. **GPT consistently 3-8x slower than other models.** 6.5 min (solve),
   4 min (evaluate), 8 min (revise) vs 0.5–3.5 min for Gemini and Opus.
   Same pattern as arena run 1. Total wall time is bottlenecked by GPT.

### Fundamental Design Issues

7. **Agents critique conversation summaries, not branch deliverables.** The
   conversation-extracted solutions are 10-15 line PLAN/CHANGES summaries.
   The actual `recommendations.md` files on the branches are 66–375 lines.
   Agents critique summaries and the consensus loop scores summaries. The
   judge selected the weakest deliverable (Gemini, 66 lines) as the base
   because its summary was the cleanest, while the actual best deliverable
   (Opus, 375 lines) looked like "just another option" in summary form.

8. **Self-selection bias in judge voting.** The judge picked its own solution
   as the base. With only summaries to compare, there wasn't enough signal
   to overcome familiarity bias. A better design: each agent votes on the
   best OTHER solution (excluding itself), and consensus requires 2/3
   agreement.

## Observability Improvements Needed

1. **Log messages should reference models, not just aliases.** "Agent agent_a
   finished" is meaningless without cross-referencing the alias mapping.
   Should say "Agent agent_a (gemini) finished" or just "gemini finished."

2. **state.json should be YAML.** JSON is fine for machines but hard for
   humans to scan during manual step-by-step runs. Consider `ruamel.yaml`.

3. **Archive directory structure is confusing.**
   - `artifacts/` holds "live" externalized state fields (overwritten each
     round). The flat `00-01-solve-*.md` files are point-in-time archives.
     This dual structure is not documented and confusing.
   - The second number in the filename (`01`) is the phase number (solve=1,
     evaluate=2, revise=3, verify=4), but both `solve` and `analysis` get
     phase number `01` because they're extracted in the same phase. This
     makes the numbering scheme misleading. Use phase names instead of numbers.

4. **No per-agent timing in status output.** The status command shows phase
   progress but not when each agent finished. Had to read the log manually.

5. **No indication of which agents are still running during polling.**

6. **Track branch → agent mapping.** Currently `branch_names` is empty
   because the API doesn't return it. We should fetch branches from the repo
   after the solve phase (e.g., `git ls-remote`) and match them to agents by
   commit timing or content. This mapping is essential for branch-aware
   critique and for the final report.

## Friction Points

1. **Step mode requires cold CLI invocations.** Each step is a fresh `pixi run`
   with ~10s startup overhead. No "watch" mode or progress bar.

2. **No way to inspect judge verdict on CONTINUE.** The most interesting
   artifact for understanding arena flow is discarded.

3. **No way to compare branch files.** The orchestrator doesn't fetch, diff,
   or present the agents' actual committed files. All comparison happens on
   conversation summaries.

## Collaboration Difficulties & Inefficiencies

1. **Agents critique summaries, not deliverables.** See Issue #7 above.

2. **GPT bottleneck wastes Gemini/Opus idle time.** The parallel wait means
   fast agents sit idle for 5-8 minutes. No way to start the next phase for
   finished agents early (and it's not clear this would be desirable
   architecturally).

3. **Judge self-selection bias.** See Issue #8 above.

4. **No branch cross-inspection.** Agents cannot see each other's committed
   files. The `--branch-only` mode exists but can't work because
   `branch_names` is empty and agents aren't told how to find the branches.

---

## Recommendations for Arena Improvements

### Must-fix (critical for correctness)

1. **Fix the `wait_for_followup` race condition.** Require agent status ==
   FINISHED before extracting the response text, not just a new message
   count. This caused the verdict to be misclassified.

2. **Always persist verdict text.** Save `verdict_text` on every verify
   outcome (CONSENSUS, CONTINUE, or max-rounds), not just on arena
   completion.

3. **Track branch → agent mapping.** After the solve phase, discover agent
   branches (via `git ls-remote` or the Cursor dashboard API) and persist
   them in `state.branch_names`. This is a prerequisite for branch-aware
   features.

### Should-fix (quality of collaboration)

4. **Use branch files as the source of truth for critique.** After each
   solve/revise phase, fetch each agent's branch and read the target
   deliverable file(s). Use these as the `solutions` content in evaluate
   and verify prompts. Fall back to conversation extraction only if no
   branch changes are detected. (Same recommendation as run 1.)

5. **Replace single-judge verdict with multi-agent voting.** Each agent votes
   on the best solution *excluding its own*. Require 2/3 agreement for
   consensus. This eliminates self-selection bias and produces more robust
   consensus. The current single-judge approach has a structural conflict of
   interest.

6. **Improve verdict extraction reliability.** Add a re-prompt specifically
   for verdict formatting. Make the keyword fallback smarter (look for
   "decision: CONSENSUS" patterns, prefer last occurrence, etc.).

### Should-fix (UX / observability)

7. **Log messages should include model names**, not just aliases.
8. **Use YAML for state file** for human readability during step-by-step runs.
9. **Redesign archive naming.** New scheme:
   `{round:02d}-{phase:02d}-{phase_name}-{model}-{artifact}-{uid}.md`
   e.g. `00-01-solve-gemini-solution-e41f08.md`. Sorts correctly in `ls`
   (round → phase number → phase name → model → artifact type → uid).
   Drop the agent letter (use model name instead). Rename `artifacts/` to
   reflect that it holds live/current conversation extracts (e.g.
   `transcripts/` or `current/`), and make it cumulative (versioned by
   round) rather than overwriting.
10. **Add per-agent timing** to state and status output.
11. **Capture agent metadata from status response.** The API returns
    `summary`, `linesAdded`, `filesChanged` per agent -- useful for the
    report and for understanding agent behavior.

---

## API Findings

### Available models

```
claude-4.6-opus-high-thinking
gpt-5.2
gpt-5.2-high
gpt-5.2-codex-high
gemini-3-pro  (via docs; not listed in /models endpoint)
```

**Faster GPT option:** `gpt-5.2` (no `-codex-high` suffix) is available and
likely faster. Worth testing as a replacement for the current `gpt-5.2-codex-high`
which is consistently 3-8x slower than other models. Also `gpt-5.2-high` exists
as a middle ground.

### Branch names ARE in the API

The `status()` response contains `target.branchName`:

```json
{
  "target": {
    "branchName": "cursor/ha-backup-recommendations-455b",
    "prUrl": "https://github.com/maresb/homeassistant-config/pull/1"
  }
}
```

The code currently only checks the `launch()` response (which doesn't have it).
**Fix:** read `branchName` from `status()` after polling completes.

Branch → agent mapping for this run:

| Model | Branch | PR |
|-------|--------|-----|
| Gemini | `cursor/ha-backup-recommendations-455b` | PR #1 |
| GPT | `cursor/ha-backup-recommendations-df39` | PR #3 |
| Opus | `cursor/home-assistant-backup-strategy-d842` | PR #2 |

### PRs are always created

Each agent opens a PR automatically. The launch API does not appear to expose
a parameter to suppress this. The status response has
`openAsCursorGithubApp: false` and `skipReviewerRequest: false` but it's
unclear if these are settable at launch time. This creates 3 superfluous PRs
per arena run that need manual cleanup. **Investigate:** whether the launch
body accepts `target` options to control PR creation, or whether we need to
close PRs via `gh` CLI after the run.

### pixi startup overhead

The ~10s per `pixi run arena step` is pixi environment resolution, not API
latency. Not a fixable issue within the arena -- it's pixi's startup cost.
A `--watch` mode that stays resident would avoid this, but may not be worth
the complexity. The step command itself is fast once running.
