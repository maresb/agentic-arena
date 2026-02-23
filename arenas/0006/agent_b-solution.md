## PLAN — Publication-Readiness Re-Audit (post-update)

The main branch has been updated to address the majority of feedback from the initial audit. This re-audit evaluates the current state and identifies remaining issues.

### Summary of resolved items

The following items from the initial audit have been fully addressed:

1. **LICENSE added** — MIT License with proper copyright (Ben Mares, 2026). Critical blocker resolved.
2. **Internal diary files removed** — `TODO.md`, `TODO_IMPROVEMENTS.md`, `execution-plan.md`, `execution-plan2.md`, `arena-run-summary.md`, `arena-run-summary2.md`, `arena-run-summary3.md` all deleted from the default branch.
3. **proposal.md folded into README** — Design rationale integrated as a concise "Design" section; original file deleted. No outdated code samples remain.
4. **pixi.toml metadata updated** — `name = "agentic-arena"`, `authors` set to actual maintainer with proper email.
5. **TODO comment in api.py removed** — No in-code TODOs remain in any Python file.
6. **Dockerfile pixi version synchronized** — Both Dockerfile and CI now use `v0.63.2`.
7. **pyproject.toml added** — Proper package metadata with `console_scripts` entrypoint, MIT license declaration, and hatch build system.
8. **Project renamed** — From `cursor-agentic-arena` to `agentic-arena` (README clone URL, pixi.toml, pyproject.toml all consistent).
9. **README test count updated** — Now says "227 tests" (actual count is 224 passing + 3 skipped; close enough).
10. **Integration test instructions fixed** — README now shows the correct `RUN_INTEGRATION_TESTS=1` opt-in guard.
11. **cost_per_1k documented as rough estimates** — Comment added in orchestrator.py.
12. **Agent poll timeout increased** — `AGENT_POLL_TIMEOUT = 1800` (30 min) added for long-running agents.

### Remaining issues (prioritized)

### 1. README consensus threshold mismatch (Medium — documentation bug)

**Problem:** The README header diagram says `score >= 8` but the actual consensus threshold in `arena/phases.py` line 520 is `final_score >= 9`. This was changed in a prior commit (raising threshold from 8 to 9) but the README was not updated to match.

**Recommendation:** Update the README diagram from `score >= 8` to `score >= 9`.

### 2. Stale "judge selection" bullet in crash recovery section (Low — documentation)

**Problem:** README line 229–231 says "Judge selection is persisted. The verify phase saves the selected judge before sending the verdict prompt, so a crash won't re-select a different judge on restart." The system no longer uses a single judge — it uses multi-agent voting where all agents evaluate and vote. There is no judge selection step.

**Recommendation:** Remove or replace the bullet. Could say something like "All agents evaluate in parallel; each agent's progress is tracked individually."

### 3. Stale extraction troubleshooting section (Low — documentation)

**Problem:** README lines 388–392 describe "Extraction failures (no `<solution>` tag)" with XML tag retry behavior. The system no longer uses XML tags — it now uses file-committed outputs fetched from agent branches. The `extract_xml_section` function was removed in a prior commit.

**Recommendation:** Rewrite this section to describe the actual extraction flow: agents commit files to their branches; if a file is missing, the orchestrator re-prompts up to 3 times asking the agent to commit.

### 4. Stale module descriptions in project structure (Low — documentation)

**Problem:** The "Project structure" section has two inaccurate descriptions:
- `extraction.py` is described as "XML tag parsing, Verdict model, fallback heuristics" — it should be "JSON verdict parsing, conversation helpers"
- The key types table references `Verdict` but the actual class is `VoteVerdict`
- `test_extraction.py` is described as "XML parsing, verdict model, fallbacks" — should match the module description

**Recommendation:** Update the one-line descriptions to reflect the current implementation.

### 5. `arena/conversations/` not gitignored (Low — hygiene)

**Problem:** The `.gitignore` covers `arena/artifacts/` and `arena/state.yaml` but not `arena/conversations/`. This directory exists locally (from a prior run) and shows as untracked in `git status`. Could be accidentally committed.

**Recommendation:** Add `arena/conversations/` to `.gitignore`.

### 6. No CONTRIBUTING.md (Low — nice-to-have for OSS)

**Problem:** The project has excellent README documentation for users but no contributor-facing guide. The pre-commit config, dev container setup, and commit conventions are discoverable but not documented.

**Recommendation:** A minimal CONTRIBUTING.md is standard for OSS projects but not a blocker. Could be deferred to post-launch.

---

## CHANGES — Precise Change Descriptions

### Change 1: Fix consensus threshold in README

```diff
 generate --> evaluate
-               |-- CONSENSUS (score >= 8) --> done
-               |-- CONTINUE  (score < 8)  --> generate (next round)
+               |-- CONSENSUS (score >= 9) --> done
+               |-- CONTINUE  (score < 9)  --> generate (next round)
                '-- max rounds reached     --> done
```

### Change 2: Fix crash recovery bullet about judge selection

Replace:

```markdown
- **Judge selection is persisted.** The verify phase saves the selected judge
  before sending the verdict prompt, so a crash won't re-select a different
  judge on restart.
```

With something like:

```markdown
- **Multi-agent voting.** All agents evaluate and vote in parallel.
  Each agent's progress is tracked individually, so a crash during the
  evaluate phase only re-processes agents that haven't finished.
```

### Change 3: Fix extraction troubleshooting section

Replace:

```markdown
### Extraction failures (no `<solution>` tag)

When an agent's response lacks the expected `<solution>` XML tag, the
orchestrator sends a re-prompt asking the agent to reformat. If the retry also
fails, the full response is used as the solution (with a warning logged).
```

With something like:

```markdown
### Missing agent output files

Agents are expected to commit their output files (solution, analysis, critique,
verdict) to their branch. If a file is missing after the agent finishes, the
orchestrator re-prompts up to 3 times asking the agent to commit it. If all
retries fail, the output is treated as empty (with an error logged).
```

### Change 4: Fix module descriptions in project structure

```diff
-  extraction.py      XML tag parsing, Verdict model, fallback heuristics
+  extraction.py      JSON verdict parsing, conversation helpers

-  test_extraction.py   XML parsing, verdict model, fallbacks
+  test_extraction.py   Verdict parsing, conversation helpers
```

In the key types table:

```diff
-| `Verdict` | `extraction.py` | Parsed judge verdict with decision, score, etc. |
+| `VoteVerdict` | `extraction.py` | Parsed agent verdict with score, votes, divergences |
```

### Change 5: Add arena/conversations/ to .gitignore

```diff
 arena/artifacts/
+arena/conversations/
 arenas/
```
