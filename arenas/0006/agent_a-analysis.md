## RISKS — Known risks, edge cases, trade-offs.
- **Consensus Threshold**: The threshold is set to 8 (down from 9) to allow for realistic convergence, but this might accept slightly less perfect solutions.
- **Agent Sandbox**: Users must still be cautious with `verify_commands` as they run in the agent's environment (though cloud-boxed, side effects could be possible if configured insecurely).
- **Cost Visibility**: The project lacks built-in cost tracking for the LLM usage; users must rely on the Cursor dashboard.

## OPEN QUESTIONS — Uncertainties requiring verification.
- **PyPI Distribution**: If the project is intended for PyPI, `pyproject.toml` needs more metadata (classifiers, description, etc.). Currently, it seems optimized for `pixi`/source usage.
- **Long-term Maintenance**: With `TODO.md` gone, where are future tasks tracked? (Presumably GitHub Issues).
