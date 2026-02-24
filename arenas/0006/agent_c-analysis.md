## RISKS
- **Residual doc drift:** A few README sections still refer to judge selection
  and XML tags. Leaving them can mislead users about failure modes and workflows.
- **Gitignore friction:** Keeping `arenas/` ignored can confuse users running
  the arena on repos that also ignore that path; they may need `git add -f`.
- **Community expectations risk:** Without CONTRIBUTING/SECURITY/CoC, incoming
  contributors lack guidance on behavior, triage, and disclosure.
- **CI scope risk:** Adding coverage or stricter checks can slow CI and require
  ongoing maintenance; skipping coverage leaves quality opaque.
- **External dependency drift:** Cursor docs URLs may change; broken links
  increase support burden.

## OPEN QUESTIONS
- Should the README remove all judge/verify language and XML-tag troubleshooting,
  or do you plan to reintroduce those concepts in code?
- Do you want `arenas/` outputs to be trackable by default (adjust `.gitignore`)
  or remain ignored with explicit `git add -f` guidance?
- Will you add standard community docs (CONTRIBUTING/SECURITY/CoC), and should
  they include a lightweight governance model or maintainer contact?
- Should test coverage be reported in CI (and shown via badge), or is unit-test
  pass/fail sufficient for this project?
- Should integration tests remain manual-only, or do you want a scheduled CI
  job with dedicated secrets?
