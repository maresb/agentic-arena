## RISKS — Known risks, edge cases, trade-offs.
- **Consensus Threshold**: Lowering the consensus threshold to 8 allows for slightly more divergence, potentially accepting suboptimal solutions, but it aligns with the documented intent.
- **Data Leakage**: The `arena/conversations/` directory was previously unignored, which could lead to accidental commitment of sensitive conversation data. This is mitigated by the `.gitignore` update.
- **Cost Management**: Running multiple agents for multiple rounds can be expensive. Users should monitor usage via the Cursor dashboard as the tool does not currently track costs (tracked as a TODO).
- **API Reliability**: The tool relies heavily on the Cursor Cloud Agents API. Rate limits or downtime could impact stability (mitigated by retry logic).

## OPEN QUESTIONS — Uncertainties requiring verification.
- **Distribution Model**: Is the project intended to be distributed primarily via `pixi` or as a PyPI package? If the latter, `pyproject.toml` metadata needs expansion.
- **Agent Sandbox Security**: While agents run in cloud VMs, users should exercise caution when running the generated code locally, especially `verify_commands`.
- **Maintenance of `proposal.md`**: Should the design proposal be kept as a historical artifact or updated as documentation? Currently kept as is.
