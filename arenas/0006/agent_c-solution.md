## PLAN
1. Identify release blockers (license, doc/code mismatch, gitignore conflicts) because they directly affect legal viability and user comprehension.
2. Capture high/medium/low priority cleanup items (internal artifacts, community files, CI/coverage, metadata) to make the repo look professional.
3. Document security scan results and testing/CI gaps to give a complete publication-readiness view.

## CHANGES
### Publication-Readiness Report (Agent C)
**Status:** NOT READY — P0 blockers below.

#### P0 — Blockers (fix before making public)
1) **Missing LICENSE**
   - **Evidence:** No LICENSE* file in repo root (Glob search returned 0).
   - **Impact:** No clear legal permission to use/redistribute.
   - **Action:** Add a LICENSE file and reference it in README.

2) **Docs are out of sync with the code**
   - **Evidence:**
     - README describes a 4-phase loop (solve/evaluate/revise/verify) and `state.json`,
       but code uses a 2-phase generate/evaluate loop with `state.yaml`
       (`arena/state.py`, `arena/phases.py`, `arena/orchestrator.py`).
     - README documents `--branch-only`, which does not exist in the CLI (`arena/__main__.py`).
     - README says integration tests run when CURSOR_API_KEY is set, but tests
       require `RUN_INTEGRATION_TESTS=1` (`tests/test_integration.py`).
     - Proposal and execution-plan docs describe the older 4-phase design and XML parsing.
   - **Impact:** Users will follow incorrect instructions and misunderstand behavior.
   - **Action:** Update README and docs to reflect current architecture (generate/evaluate,
     YAML state, file-based artifacts, current CLI flags). Either update
     `proposal.md` / `execution-plan*.md` to current state or clearly mark them as
     historical design notes.

3) **`arenas/` is gitignored but prompts require commits there**
   - **Evidence:** `.gitignore` ignores `arenas/`; prompts instruct agents to commit
     `arenas/NNNN/<alias>-solution.md` etc. (`arena/prompts.py`).
   - **Impact:** Agents cannot commit outputs without `git add -f`, causing failures.
   - **Action:** Resolve the conflict by either:
     - removing/relaxing the `arenas/` ignore rule and adding a narrower ignore
       (or subdir `.gitignore`) for local-only artifacts, or
     - explicitly instructing `git add -f` in prompts/documentation.

#### P1 — High priority (professional release quality)
4) **Internal run summaries and plans likely not intended for public release**
   - **Evidence:** `arena-run-summary*.md`, `execution-plan*.md` include internal
     logs, other repo names, agent IDs, and debugging details.
   - **Impact:** Looks like internal artifacts; may leak irrelevant context.
   - **Action:** Move to `docs/notes/` (with a short context header) or remove
     before publication. Sanitize any external repo details if kept.

5) **Missing community files**
   - **Evidence:** No `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, or `SECURITY.md`.
   - **Impact:** Contributing expectations and vulnerability handling are unclear.
   - **Action:** Add standard community docs and link them from README.

6) **README examples reference a different repo URL**
   - **Evidence:** README clone command points to `https://github.com/maresb/cursor-agentic-arena.git`.
   - **Impact:** Confusing or wrong for public users.
   - **Action:** Update to the correct canonical repository URL or use a placeholder.

#### P2 — Medium priority
7) **No coverage reporting**
   - **Evidence:** CI runs tests but does not report coverage (`.github/workflows/ci.yml`).
   - **Impact:** Harder for contributors to gauge test depth.
   - **Action:** Add coverage tooling (e.g., pytest-cov) and optional badge.

8) **External link verification**
   - **Evidence:** README links to `https://docs.cursor.com` and other Cursor docs.
   - **Impact:** Broken links are unprofessional and confusing.
   - **Action:** Validate and update all external URLs in README and docstrings.

9) **TODOs in code/docs**
   - **Evidence:** TODO in `arena/api.py` and TODO sections in README/TODO.md.
   - **Impact:** Acceptable for dev, but better as GitHub issues for a public repo.
   - **Action:** Move roadmap items to issues; keep README focused on usage.

#### P3 — Low priority polish
10) **Project metadata cleanup**
   - **Evidence:** `pixi.toml` name/author is generic ("workspace", "Cursor Agent").
   - **Action:** Update metadata to actual project name/maintainer.

11) **Add standard repo hygiene files**
   - **Action:** Consider `.editorconfig`, `CHANGELOG.md`, and issue templates.

#### Security scan notes
- No hardcoded secrets detected. Only placeholder API key strings in README.
- `.env` is gitignored; no secret tokens found in repo content.
