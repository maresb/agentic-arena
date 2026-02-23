## PLAN — Numbered key decisions with rationale.
1.  **Merge Upstream Changes**: Merged `main` branch to incorporate operator feedback and latest updates.
2.  **Resolve License Conflict**: Accepted the upstream `LICENSE` file (Copyright Ben Mares) over the generated one, as it reflects the correct copyright holder.
3.  **Accept TODO Deletion**: Accepted the deletion of `TODO.md` from upstream, assuming tasks are tracked elsewhere or completed.
4.  **Preserve Critical Fixes**: Verified and preserved the fix for consensus logic (`score >= 8`) in `arena/phases.py` and the security improvement in `.gitignore` (`arena/conversations/`).
5.  **Clean Development Artifacts**: Confirmed removal of `arena-run-summary*.md` and `execution-plan*.md`.

## CHANGES — Unified diff or precise change descriptions.
- **Merged**: `origin/main` into `cursor/open-source-readiness-review-dd1f`.
- **Modified**: `arena/phases.py` (preserved)
  - `consensus = final_score >= 8 and winner is not None`
- **Modified**: `.gitignore` (preserved)
  - Added `arena/conversations/`
- **Deleted**: `TODO.md` (sync with upstream).
- **Deleted**: Temporary run summaries and execution plans (sync with upstream/cleanup).
