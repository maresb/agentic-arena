## RISKS
- **License choice risk:** Picking an incompatible license later could force
  re-licensing or limit adoption; delaying a license blocks legal use now.
- **Doc/code divergence risk:** Updating docs to match the 2-phase design may
  conflict with the original 4-phase vision. If the 4-phase model is intended,
  the code must be changed instead.
- **Gitignore conflict risk:** Relaxing `arenas/` ignore rules can cause local
  run artifacts to be accidentally committed. If you keep it ignored, prompts
  must explicitly guide `git add -f`.
- **Removing internal artifacts risk:** Deleting run summaries may lose useful
  historical debugging context; keeping them may look unprofessional or leak
  unrelated project details.
- **CI scope risk:** Adding coverage or stricter checks can slow CI or cause
  failures on edge platforms; requires maintenance commitment.
- **External dependency risk:** README links to Cursor docs may drift; outdated
  links create confusion and increase support load.

## OPEN QUESTIONS
- Which open-source license should be applied (MIT, Apache-2.0, GPL, etc.)?
- Is the **current** intended workflow the 2-phase generate/evaluate loop, or
  should the repository return to the 4-phase solve/evaluate/revise/verify
  model described in README/proposal?
- Should `proposal.md` and `execution-plan*.md` be kept as historical design
  artifacts (with headers marking them as such), or removed/moved to docs?
- Do you want the internal `arena-run-summary*.md` files public? If yes, should
  they be sanitized and moved under `docs/`?
- What is the canonical repository URL to show in README clone examples?
- Should CI run on `main` only, or is the default branch different?
- Should integration tests ever run in CI (with secrets), or remain manual-only?
- How should `arenas/` outputs be handled: tracked (for agent commits) or
  ignored (for local runs), and how should the prompts/docs reflect that?
