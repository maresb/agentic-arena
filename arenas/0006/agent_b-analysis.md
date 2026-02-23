## RISKS — Known Risks, Edge Cases, Trade-offs

### R1: All critical blockers resolved — project is publication-ready

The main branch update addressed all high-priority items from the initial audit:
- MIT License added (legal blocker resolved)
- Internal diary files removed (professionalism)
- Stale metadata fixed (pixi.toml, authors, project name)
- In-code TODOs removed
- Pixi version synchronized
- pyproject.toml added with proper packaging

The remaining issues are exclusively documentation accuracy items (Low severity). None would prevent publication.

### R2: Consensus threshold mismatch is the most visible remaining issue (Medium)

The README's header diagram is one of the first things a visitor sees. It shows `score >= 8` as the consensus threshold, but the code uses `>= 9`. This is a factual error in the most prominent part of the documentation. While it won't cause runtime problems (the code is correct), it will confuse anyone reading the README and then inspecting the code.

**Risk:** A contributor or user may file a bug report thinking the threshold is wrong in the code, or may misunderstand why consensus wasn't reached when scores are 8.

### R3: Stale crash recovery and troubleshooting sections reference removed features (Low)

Two README sections reference features from the old 4-phase architecture:
1. "Judge selection is persisted" — the judge/verify phase was removed in favor of multi-agent voting
2. "Extraction failures (no `<solution>` tag)" — XML tag extraction was removed in favor of file-committed outputs

These won't cause runtime issues but will confuse readers who try to map the documentation to the actual codebase.

### R4: No hardcoded secrets or sensitive data (Verification — PASS)

Re-verified after the update:
- No API keys, tokens, or passwords in any source file
- `.env` remains properly gitignored
- The internal diary files that contained personal repo references (`maresb/homeassistant-config`) and agent IDs have been removed
- Integration tests still properly guarded behind `RUN_INTEGRATION_TESTS=1`
- The README's example API key uses an obvious placeholder format

### R5: Code quality remains excellent (Verification — PASS)

Full test/lint/format/typecheck suite passes on the updated codebase:
- **Tests:** 224 passed, 3 skipped, 0 failed
- **Linter:** All checks passed (ruff)
- **Formatter:** 19 files already formatted
- **Type checker:** No issues found (mypy, 9 source files)
- **CI:** Properly configured for all four checks

### R6: Local arena artifacts in arena/ directory (Low)

The `arena/` Python package directory contains local run artifacts:
- `arena/state.yaml` — gitignored ✓
- `arena/artifacts/` — gitignored ✓
- `arena/conversations/` — **NOT gitignored** ✗

The `conversations/` directory contains JSON dumps of agent conversations from a prior run. While unlikely to be accidentally committed (the directory isn't staged), adding it to `.gitignore` would be proper hygiene.

### R7: README test count slightly off (Negligible)

README says "227 tests" but actual count is 224 passed + 3 skipped = 227 total (224 run). This is accurate if counting total test functions; the skipped tests are integration tests requiring `RUN_INTEGRATION_TESTS=1`. Not worth changing.

### R8: The `arenas/` gitignore pattern is correct for the intended workflow

After reviewing the agent prompts and commit convention more carefully: agents commit to `arenas/NNNN/` on their own branches, not on the main branch. The `.gitignore` entry prevents local orchestrator output from being committed to the operator's working copy. Agents work on separate branches where the `.gitignore` also applies, but agents use `git add -f` (or the Cursor agent infrastructure handles it). This is the correct design — no change needed.

---

## OPEN QUESTIONS — Uncertainties Requiring Verification

### Q1: Should the remaining documentation fixes be done before or after publication?

The five remaining issues are all documentation accuracy items (Low to Medium severity). Options:
1. Fix before publication (cleanest, ~15 min of work)
2. Publish as-is and fix in a follow-up PR (acceptable — none are blockers)
3. Open issues to track them (standard OSS practice)

**Recommendation:** Fix the consensus threshold mismatch (most visible) before publication. The others can be follow-ups.

### Q2: Is the README's "227 tests" count methodology clear?

The README says "227 tests" but `pytest` reports "224 passed, 3 skipped". The 227 is the total count including skipped integration tests. This is technically correct but could confuse someone who runs `pixi run test` and sees "224 passed". Consider saying "224+ tests" or "227 tests (3 integration tests skipped without API key)".

### Q3: Publication readiness summary (updated)

| Category | Status | Notes |
|----------|--------|-------|
| License | **PASS** | MIT License added |
| Code quality | **PASS** | All tests, lint, format, typecheck pass |
| Security | **PASS** | No hardcoded secrets, proper env var handling |
| Documentation | **GOOD** | 5 minor accuracy issues remain (see PLAN) |
| CI/CD | **PASS** | GitHub Actions properly configured |
| Test coverage | **GOOD** | 224 tests across 9 test files |
| Internal files | **PASS** | All diary/planning files removed |
| Metadata | **PASS** | pixi.toml, pyproject.toml properly configured |
| Packaging | **PASS** | Editable install, console_scripts entrypoint |
| Dev environment | **PASS** | Devcontainer, pre-commit hooks configured |

**Overall assessment:** The project is publication-ready. The remaining items are minor documentation accuracy fixes that do not block release. The codebase is clean, well-tested, properly licensed, and professionally presented.
