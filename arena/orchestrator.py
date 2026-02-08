"""Main orchestrator loop and report generation.

The orchestrator is a simple FSM: solve -> evaluate -> revise -> verify,
looping back to evaluate until consensus or max rounds.  All progress
lives in the state file, so the process can be killed and restarted at
any point.

The core primitive is :func:`step_once`, which executes exactly one phase
transition.  :func:`run_orchestrator` is a convenience wrapper that loops
``step_once`` until the arena is complete.
"""

from __future__ import annotations

import hashlib
import logging
import os

from arena.api import CursorCloudAPI
from arena.phases import step_evaluate, step_revise, step_solve, step_verify
from arena.state import (
    ArenaState,
    Phase,
    load_state,
    sanitize_filename_component,
    save_state,
)

DEFAULT_ARENA_DIR = "arenas/0001"

logger = logging.getLogger("arena")

# ---------------------------------------------------------------------------
# Phase dispatch table
# ---------------------------------------------------------------------------

PHASE_HANDLERS = {
    Phase.SOLVE: step_solve,
    Phase.EVALUATE: step_evaluate,
    Phase.REVISE: step_revise,
    Phase.VERIFY: step_verify,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api() -> CursorCloudAPI:
    """Create a :class:`CursorCloudAPI` from the ``CURSOR_API_KEY`` env var."""
    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CURSOR_API_KEY environment variable is not set. "
            "Export your Cursor API key to proceed."
        )
    return CursorCloudAPI(api_key)


_PHASE_NUMBER = {"solve": 1, "evaluate": 2, "revise": 3, "verify": 4}


def _content_uid(content: str) -> str:
    """Return a short deterministic UID from content (first 6 hex chars of SHA-256)."""
    return hashlib.sha256(content.encode()).hexdigest()[:6]


def _archive_artifact(arena_dir: str, name: str, content: str) -> None:
    """Write an artifact file, skipping if it already exists (deduplication)."""
    path = os.path.join(arena_dir, name)
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _archive_round(state: ArenaState, arena_dir: str) -> None:
    """Archive the current round's outputs using deterministic naming.

    Naming scheme: ``{round:02d}-{phase:02d}-{phase_name}-{letter}-{model}-{uid}.md``
    where *uid* is derived from content (SHA-256 prefix) for deduplication.
    Files already present on disk are not overwritten.
    """
    rnd = state.round

    for alias in state.alias_mapping:
        letter = sanitize_filename_component(alias.split("_")[1])  # "agent_a" → "a"
        model = sanitize_filename_component(
            str(state.alias_mapping.get(alias, "unknown"))
        )

        solution = state.solutions.get(alias)
        if solution:
            uid = _content_uid(solution)
            name = f"{rnd:02d}-{_PHASE_NUMBER['solve']:02d}-solve-{letter}-{model}-{uid}.md"
            _archive_artifact(arena_dir, name, solution)

        analysis = state.analyses.get(alias)
        if analysis:
            uid = _content_uid(analysis)
            name = f"{rnd:02d}-{_PHASE_NUMBER['solve']:02d}-analysis-{letter}-{model}-{uid}.md"
            _archive_artifact(arena_dir, name, analysis)

        critique = state.critiques.get(alias)
        if critique:
            phase_num = _PHASE_NUMBER["evaluate"]
            uid = _content_uid(critique)
            name = f"{rnd:02d}-{phase_num:02d}-critique-{letter}-{model}-{uid}.md"
            _archive_artifact(arena_dir, name, critique)

    # Archive verdict if present
    if state.final_verdict and state.phase == Phase.DONE:
        judge_letter = sanitize_filename_component(
            state.judge_history[-1].split("_")[1]
        )
        judge_model = sanitize_filename_component(
            str(state.alias_mapping.get(state.judge_history[-1], "unknown"))
        )
        uid = _content_uid(state.final_verdict)
        phase_num = _PHASE_NUMBER["verify"]
        name = f"{rnd:02d}-{phase_num:02d}-verify-{judge_letter}-{judge_model}-{uid}.md"
        _archive_artifact(arena_dir, name, state.final_verdict)


def generate_final_report(state: ArenaState, arena_dir: str) -> None:
    """Generate a final Markdown report summarizing the arena run."""
    consensus = state.consensus_reached if state.consensus_reached is not None else True
    alias_display = {k: str(v) for k, v in state.alias_mapping.items()}

    report_lines = [
        "# Arena Report",
        "",
        f"**Task:** {state.config.task}",
        f"**Rounds:** {state.round}",
        f"**Consensus:** {'Yes' if consensus else 'No'}",
        f"**Alias mapping:** {alias_display}",
        "",
        "---",
        "",
        "## Final Verdict",
        "",
        state.final_verdict or "N/A",
        "",
        "---",
        "",
        "## Final Solutions",
        "",
    ]
    for alias, solution in state.solutions.items():
        model = state.alias_mapping.get(alias, "unknown")
        report_lines.append(f"### {alias} ({model})")
        report_lines.append("")
        report_lines.append(solution)
        report_lines.append("")

    if state.analyses:
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## Final Analyses")
        report_lines.append("")
        for alias, analysis in state.analyses.items():
            model = state.alias_mapping.get(alias, "unknown")
            report_lines.append(f"### {alias} ({model})")
            report_lines.append("")
            report_lines.append(analysis)
            report_lines.append("")

    if state.verify_results:
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## Verify Command Results")
        report_lines.append("")
        for i, result in enumerate(state.verify_results):
            cmd = (
                state.config.verify_commands[i]
                if i < len(state.config.verify_commands)
                else f"command {i + 1}"
            )
            report_lines.append(f"### `{cmd}`")
            report_lines.append("")
            report_lines.append(result)
            report_lines.append("")

    # Print PR URL for the winning branch if available
    if state.consensus_reached and state.branch_names:
        # Determine winner from verdict's base_solution field or first alias
        from arena.extraction import parse_verdict

        winner_alias = None
        if state.final_verdict:
            verdict = parse_verdict(state.final_verdict)
            if verdict.base_solution and verdict.base_solution in state.branch_names:
                winner_alias = verdict.base_solution
        if not winner_alias:
            winner_alias = next(iter(state.branch_names), None)

        if winner_alias and winner_alias in state.branch_names:
            branch = state.branch_names[winner_alias]
            repo = state.config.repo
            if not repo.startswith("https://"):
                repo_url = f"https://github.com/{repo}"
            else:
                repo_url = repo
            pr_url = (
                f"{repo_url}/compare/{state.config.base_branch}...{branch}?expand=1"
            )
            report_lines.append("---")
            report_lines.append("")
            report_lines.append("## Merge Winner")
            report_lines.append("")
            report_lines.append(
                f"**Winner:** {winner_alias} "
                f"({state.alias_mapping.get(winner_alias, 'unknown')})"
            )
            report_lines.append(f"**PR URL:** {pr_url}")
            report_lines.append("")

    if state.token_usage:
        # Rough cost estimates per 1K tokens (input+output blended)
        cost_per_1k: dict[str, float] = {
            "opus": 0.075,
            "gpt": 0.060,
            "gemini": 0.035,
        }
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## Token Usage & Cost Estimates")
        report_lines.append("")
        total_cost = 0.0
        for alias, tokens in state.token_usage.items():
            model = str(state.alias_mapping.get(alias, "unknown"))
            rate = cost_per_1k.get(model, 0.05)
            cost = (tokens / 1000) * rate
            total_cost += cost
            report_lines.append(
                f"- **{alias}** ({model}): {tokens:,} tokens (~${cost:.2f})"
            )
        report_lines.append(
            f"- **Total**: {sum(state.token_usage.values()):,} tokens "
            f"(~${total_cost:.2f})"
        )
        report_lines.append("")

    report_path = os.path.join(arena_dir, "report.md")
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
    logger.info("Final report written to %s", report_path)


def step_once(arena_dir: str = DEFAULT_ARENA_DIR) -> ArenaState:
    """Execute exactly one phase transition and return the updated state.

    This is the core FSM primitive.  It loads the state, dispatches the
    current phase handler, archives outputs, saves the state, and returns.

    Raises
    ------
    FileNotFoundError
        If no state file exists.
    RuntimeError
        If the arena is already completed or CURSOR_API_KEY is missing.
    ValueError
        If the current phase has no handler (e.g. ``done``).
    """
    state_path = os.path.join(arena_dir, "state.json")
    state = load_state(state_path)
    if state is None:
        raise FileNotFoundError(
            f"No state file found at {state_path}. "
            "Use 'python -m arena init' to create one."
        )
    if state.completed:
        raise RuntimeError("Arena is already completed.")

    before_phase = state.phase
    handler = PHASE_HANDLERS.get(before_phase)
    if handler is None:
        raise ValueError(f"Unknown or terminal phase: {before_phase}")

    api = _make_api()
    logger.info("=== Round %d | Phase: %s ===", state.round, before_phase)
    handler(state, api, state_path=state_path)

    _archive_round(state, arena_dir)
    save_state(state, state_path)
    return state


def run_orchestrator(arena_dir: str = DEFAULT_ARENA_DIR) -> None:
    """Loop :func:`step_once` until the arena is complete, then report."""
    while True:
        state = step_once(arena_dir)
        if state.completed:
            break

    generate_final_report(state, arena_dir)

    consensus = (
        state.consensus_reached
        if state.consensus_reached is not None
        else state.final_verdict is not None
    )
    alias_display = {k: str(v) for k, v in state.alias_mapping.items()}
    print(f"Arena complete. Rounds: {state.round}.")
    print(
        f"Verdict: {'Consensus reached' if consensus else 'No consensus (max rounds)'}"
    )
    print(f"Alias mapping: {alias_display}")
