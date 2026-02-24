## PLAN
1. Recheck prior blockers against the updated main branch and note resolved items.
2. Identify any remaining doc/code mismatches, missing OSS hygiene files, or CI gaps.
3. Produce a refreshed, prioritized publication-readiness action list.

## CHANGES
### Publication-Readiness Report (Agent C)
**Status:** MOSTLY READY — no P0 blockers found. Address P1 items before public launch.

#### ✅ Resolved since last review
- **LICENSE added** (MIT).
- **Docs significantly updated** to the 2-phase generate/evaluate loop and YAML state.
- **Internal run summaries / execution plans removed** from repo root.
- **Repo metadata updated** (`pixi.toml` name/author + `pyproject.toml` entrypoint).

#### P1 — High priority (fix before public release)
1) **Residual doc/code mismatches remain in README**
   - **Evidence:**
     - README still mentions judge selection persistence (crash recovery section),
       but there is no judge phase in code (`arena/phases.py` is generate/evaluate).
     - Troubleshooting still references missing `<solution>` XML tags, but the
       system now requires file-committed outputs (no XML parsing path).
     - Project structure calls `extraction.py` “XML tag parsing”; actual module
       parses JSON verdicts (`VoteVerdict`) and file-based artifacts.
   - **Impact:** Users can be misled about failure modes and architecture.
   - **Action:** Update/remove the outdated README sections and align the module
     descriptions with current behavior (file-based outputs + JSON verdicts).

2) **Missing community files**
   - **Evidence:** No `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, or `SECURITY.md`.
   - **Impact:** Contribution and vulnerability handling expectations are unclear.
   - **Action:** Add standard community docs and link them from README.

#### P2 — Medium priority
3) **`arenas/` is gitignored while prompts require commits there**
   - **Evidence:** `.gitignore` ignores `arenas/`; prompts instruct agents to commit
     `arenas/NNNN/<alias>-solution.md` (`arena/prompts.py`).
   - **Impact:** If users run the arena on a repo that ignores `arenas/`, agents may
     need `git add -f` to commit outputs, causing confusion.
   - **Action:** Document the `git add -f` requirement or adjust ignore rules to
     allow tracked arena outputs when desired.

4) **No coverage reporting**
   - **Evidence:** CI runs tests but does not report coverage.
   - **Impact:** Harder for contributors to gauge test depth.
   - **Action:** Add coverage tooling (pytest-cov) and optional badge.

5) **README TODO list**
   - **Evidence:** README ends with a TODO section.
   - **Impact:** Acceptable, but better tracked as GitHub issues for a public repo.
   - **Action:** Move the TODO list to issues or a roadmap document.

#### P3 — Low priority polish
6) **External link verification**
   - **Impact:** Broken links are unprofessional and confusing.
   - **Action:** Validate all external URLs in README.

7) **Repo hygiene extras**
   - **Action:** Consider `.editorconfig`, `CHANGELOG.md`, and issue templates.

#### Security scan notes
- No hardcoded secrets detected. Only placeholder API key strings in README.
- `.env` is gitignored; no secret tokens found in repo content.
