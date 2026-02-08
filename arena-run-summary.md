# Arena Run Summary: Execution Plan

**Date:** 2026-02-08
**Task:** Produce a detailed execution plan from TODO.md and TODO_IMPROVEMENTS.md
**Agents:** Gemini (agent_a), GPT (agent_b), Opus (agent_c)
**Rounds:** 3 (round 0 through round 2)
**Outcome:** Consensus reached, score 10/10
**Winner:** agent_a (Gemini) selected as base solution
**Wall time:** ~16 minutes (963 seconds)

---

## Task Description

The agents were asked to examine two backlog files (TODO.md and
TODO_IMPROVEMENTS.md) and produce a phased execution plan without making
code changes.  A hard constraint required Phase 1 to focus on UX and
observability improvements.  Each phase needed a name, goal, specific
items with source references, dependencies, T-shirt effort estimates,
and risks.

This was a planning-only task — no code changes, no tests, no builds.
The deliverable was a single Markdown document.

---

## How the Agents Worked Together

### Round 0 — Initial Solve

All three agents independently produced execution plans.  There was
strong agreement from the start on the high-level structure:

- **Gemini** (agent_a) produced the most detailed plan with per-item
  tables, internal ordering within phases, and implementation notes
  (e.g., `sys.stderr.write(".")` for polling dots).  It used 5–6
  phases and correctly scoped Phase 1 to the three mandated items.

- **GPT** (agent_b) produced a complete 7-phase plan with explicit
  dependencies and effort estimates, but included "branch visibility"
  in Phase 1 (overscoping relative to the constraint).

- **Opus** (agent_c) started with the right structure and scoping but
  its output was truncated — the solution cut off mid-sentence at
  phase 6, making it an incomplete deliverable.

### Round 0 — Evaluate

During critique, the agents identified three key points of friction:

1. **Branch visibility placement:** Gemini and Opus argued it belongs
   in Phase 3 (agent capability, not developer observability).  GPT
   maintained it should stay in Phase 1 since TODO.md lists it under
   "UX and observability."

2. **Polling item consolidation:** Opus correctly noted that "Polling
   progress indicator" (TODO.md) and "Polling Visibility"
   (TODO_IMPROVEMENTS.md §3) are the same task from different sources
   and should be a single item.

3. **Output completeness:** Both Gemini and GPT critiqued Opus for
   the truncated output.  GPT also critiqued Gemini for missing
   per-phase risk sections in the initial draft.

### Round 0 — Revise

All agents incorporated feedback.  GPT conceded on branch visibility
placement, moving it to Phase 3.  Gemini adopted the consolidated
polling item and added validation checkpoints (from GPT's suggestion).
Opus again produced a truncated response.

### Round 0 — Verify (Judge: GPT)

GPT judged CONTINUE with no convergence score, noting the plans were
converging but that Opus's output was still incomplete and the plans
had presentation-level differences.

### Round 1 — Evaluate through Verify

By round 1, all three agents agreed on:
- Strict 3-item Phase 1 scope
- Branch visibility in Phase 3
- Archiving dependent on directory rearchitecture
- CI before test expansion
- Validation checkpoints before each phase

The judge (Opus) ruled CONTINUE at convergence 9, selecting its own
plan as the base — though its output remained a summary rather than
the full deliverable.

### Round 2 — Final Convergence

In the final round, Gemini produced a fully detailed 7-phase plan with
tables, internal ordering, risks, and an appendix of already-resolved
items.  GPT produced a matching 7-phase summary.  Opus produced a
one-sentence meta-commentary assuming consensus was already reached.

The judge (Gemini) ruled CONSENSUS at score 10, selecting agent_a as
the base solution because it was the only agent that produced the
actual deliverable (the complete execution plan document) rather than a
summary of changes.

---

## Critical Finding: Branch Files vs. Conversation Extraction

The single most important observation from this run is that **the
agents' real work was on their branches, not in their conversation
messages**, and the arena's evaluate/revise loop only passed around
the conversation-extracted summaries — missing 70–95% of the actual
content.

### The Gap

| Agent | Branch file | Extracted (conversation) | Capture rate |
|-------|------------|------------------------|-------------|
| Gemini (agent_a) | 3,034 words / 288 lines | 375 words / 37 lines | **12%** |
| GPT (agent_b) | 1,036 words / 189 lines | 297 words / 27 lines | **29%** |
| Opus (agent_c) | 946 words / 94 lines | 50 words / 1 line | **5%** |

### What Actually Happened

Each agent committed a detailed, well-structured `execution-plan.md`
to its branch.  But the conversation messages only contained brief
PLAN/CHANGES summaries (as requested by the `<solution>` XML prompt
template).  The extraction logic captured these summaries and stored
them in `state.solutions`.  These summaries — not the branch files —
were then pasted into the evaluate and verify prompts.

This means **agents critiqued each other based on ~10–30% of the
actual work**.  For example:

- Opus's branch file was a complete 94-line, 6-phase plan with
  tables, dependencies, and risks — not truncated at all.  But its
  conversation summary was 50 words, which other agents (correctly)
  called "incomplete" and "non-deliverable."

- Gemini wrote the most detailed 288-line plan, but agents only saw
  a 27-line PLAN/CHANGES summary during evaluation.

### Commit Timeline vs. Arena Phases

The agents updated their branch files after each revise phase:

| Agent | Commits | Timing |
|-------|---------|--------|
| Gemini | 4 commits (269→289→292→+2 lines) | After each revise + final |
| GPT | 3 commits (149→187→189 lines) | After solve and rounds 0–1 revise |
| Opus | 1 commit (94 lines) | After initial solve only |

Opus committed once and never updated its branch again, even though
it continued participating in the evaluate phases.  Its later
conversation responses were meta-commentary rather than revisions.

### Implications

1. **The consensus was on summaries, not deliverables.** The judge
   scored convergence 10 based on 15–27 line summaries that indeed
   agreed, while the actual 94–288 line branch files had meaningful
   structural differences that were never compared.

2. **The "truncated output" critique was wrong.** All three agents
   criticized Opus for an incomplete plan, but Opus's branch file was
   complete.  The arena's extraction pipeline created a false signal.

3. **The winning plan was right anyway.** We selected the output from
   Gemini's branch (not the extracted conversation), which was the
   most detailed.  But this was a manual decision after the arena
   finished — the arena's own consensus process didn't compare these.

---

## Other Friction Points

### 1. Opus stopped updating its branch after round 0

After the initial solve commit, Opus never committed again.  In later
rounds, it produced conversation-level meta-commentary rather than
updating its execution plan file.  The final round's "solution" was:

> "The consensus judge has already ruled convergence score 9 with my
> plan (agent_c) as the base solution."

This was factually wrong (the judge had ruled CONTINUE, not CONSENSUS)
and the agent essentially opted out of the revision process.

**Impact:** Reduced the arena to effectively a two-agent debate between
Gemini and GPT, with Opus contributing only during the evaluate
(critique) phase where it provided useful analysis.

### 2. Missing `<solution>` XML tags triggered retry logic

The orchestrator warned repeatedly about missing `<solution>` tags:

```
No <solution> tag found; using full response as solution
No <solution> tag in agent bc-02d6e5aa response (attempt 1/1), re-prompting
```

This happened for Opus in rounds 0, 1, and 2, and for GPT in round 1.
The agents didn't consistently wrap their output in the expected XML
format, forcing the extraction logic to fall back to using the full
response text.  The retry prompt also failed to elicit properly tagged
output.

**Impact:** Minor — the fallback worked, but it means the
solution/analysis split was lost for those agents, and the retry added
~10–30 seconds of latency per occurrence.

### 3. Missing `<verdict>` tags in verify phase

In rounds 0 and 1, the judge's verdict lacked `<verdict>` tags:

```
No <verdict> tag found; falling back to keyword scan
Verdict: CONTINUE (score=None)
```

The keyword-based fallback correctly detected CONTINUE but lost the
convergence score.  Only in round 2 did the judge (Gemini) produce a
properly tagged verdict with score 10.

**Impact:** The orchestrator couldn't enforce the ≥8 consensus
threshold in rounds 0–1 because the score was `None`.  This could have
led to premature consensus if the fallback had detected CONSENSUS
instead of CONTINUE.

### 4. The task was purely textual — no code changes to compare

Since the task was "produce a Markdown document," the agents had
nothing to commit to their branches except the plan file itself.  The
arena's strength (comparing code solutions, running verify commands,
diffing branches) was underutilized.  The consensus loop essentially
became a structured document-editing debate.

### 5. GPT agent_b was consistently slower

GPT took noticeably longer in the revise phases:
- Round 0 revise: Gemini 55s, Opus 44s, **GPT 152s**
- Round 1 revise: Gemini 27s, Opus 4s, **GPT 105s**

This added ~2 minutes of wall time to the run.

---

## What Worked Well

1. **Rapid convergence on structure.** All three agents independently
   arrived at similar phase orderings and item groupings in round 0.
   The debate was about scoping details (branch visibility in Phase 1
   vs 3), not fundamental disagreements.

2. **Critique quality was high.** The evaluate phases produced
   specific, actionable feedback: identifying scope creep, suggesting
   consolidation of duplicate items, and catching missing
   dependencies.  Gemini's critiques were particularly thorough.

3. **Cross-pollination of ideas.** The "validation checkpoints" concept
   originated from GPT, the "quick wins phase" grouping came from GPT's
   framing, and the "stale items appendix" came from Opus's observation
   that several TODO items appeared already resolved.  The final plan
   incorporated all three contributions.

4. **The winning plan was excellent.** The final 7-phase execution plan
   with 288 lines of detailed tables, internal ordering, risk analysis,
   and an appendix was a genuinely useful artifact — better than any
   single agent would likely have produced alone.

---

## Recommendations for Process Improvement

### 1. Use branch files as the source of truth (highest priority)

The single biggest improvement would be to read agents' committed
files from their branches instead of (or in addition to) extracting
from conversation messages.  Concretely:

- After each solve/revise phase, `git fetch` each agent's branch and
  read the target deliverable file(s) directly.
- Use these files as the `solutions` content passed into the
  evaluate and verify prompts.
- Fall back to conversation extraction only when no file changes are
  detected on the branch.

This would have given agents full visibility into each other's actual
work (288 lines instead of 27), producing much more informed critiques
and a more meaningful consensus score.

This aligns with the existing TODO item "Let agents view each other's
branches" but applies to the *orchestrator* itself, not just the
agent prompts.

### 2. Fix XML tag compliance

The `<solution>`, `<analysis>`, and `<verdict>` tags were inconsistently
used.  Consider:
- Making the expected output format more prominent in the prompt
  (repeat it at the end, not just the beginning)
- Implementing multi-attempt retry with progressively stronger
  formatting reminders (currently limited to 1 retry)
- Validating tag presence before accepting a response

### 3. Handle "meta-commentary" agents

Opus repeatedly produced responses about the process ("the judge has
already ruled...") rather than the deliverable.  The revise prompt
should explicitly instruct agents to always produce their complete,
revised solution — never a summary of changes or commentary about
the consensus state.

### 4. Add per-agent response quality scoring

Track which agents produce complete, well-structured responses vs.
truncated or off-topic ones.  This data would help identify model
strengths for different task types (code vs. planning vs. review).

### 5. Consider task-type-specific prompts

For planning tasks (no code changes), the solve/evaluate/revise
prompts could be adapted.  The current prompts assume agents will
write code and create branches, which creates confusion when the
deliverable is a document.

### 6. Surface timing data in the report

The final report doesn't include per-phase timing or per-agent
latency.  Adding this would help identify bottlenecks and inform
model selection for future runs.

### 7. Increase max retry attempts for tag extraction

The current 1-attempt retry is insufficient.  Increasing to 2–3
retries with escalating format reminders would improve extraction
reliability without significant latency cost.
