"""Main orchestrator loop and report generation.

The orchestrator is a simple FSM: solve -> evaluate -> revise,
looping back to evaluate until consensus or max rounds.  All progress
lives in the state file, so the process can be killed and restarted at
any point.

The core primitive is :func:`step_once`, which executes exactly one phase
transition.  :func:`run_orchestrator` is a convenience wrapper that loops
``step_once`` until the arena is complete.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from arena.api import CursorCloudAPI
from arena.phases import step_evaluate, step_revise, step_solve
from arena.state import (
    PHASE_NUMBERS,
    ArenaState,
    Phase,
    load_state,
    sanitize_filename_component,
    save_state,
)

ARENAS_ROOT = "arenas"


def _ensure_gitignore(root: str) -> None:
    """Create a .gitignore in *root* with ``*`` if it doesn't exist."""
    gitignore = os.path.join(root, ".gitignore")
    if not os.path.exists(gitignore):
        os.makedirs(root, exist_ok=True)
        with open(gitignore, "w") as f:
            f.write("*\n")


def next_arena_dir(root: str = ARENAS_ROOT) -> str:
    """Return the path for the next sequentially-numbered arena directory.

    Scans *root* for existing ``NNNN`` subdirectories and returns
    ``root/NNNN+1``.  Creates the *root* directory (and ``.gitignore``)
    if needed.
    """
    _ensure_gitignore(root)
    existing = sorted(
        int(d) for d in (os.listdir(root) if os.path.isdir(root) else []) if d.isdigit()
    )
    next_num = (existing[-1] + 1) if existing else 1
    return os.path.join(root, f"{next_num:04d}")


def latest_arena_dir(root: str = ARENAS_ROOT) -> str | None:
    """Return the most recent arena directory, or ``None`` if none exist."""
    if not os.path.isdir(root):
        return None
    numbered = sorted((int(d), d) for d in os.listdir(root) if d.isdigit())
    if not numbered:
        return None
    return os.path.join(root, numbered[-1][1])


def arena_number_from_dir(arena_dir: str) -> int:
    """Extract the NNNN number from an arena directory path.

    Returns 1 if the directory name is not a valid number.
    """
    basename = os.path.basename(arena_dir.rstrip("/"))
    try:
        return int(basename)
    except ValueError:
        return 1


logger = logging.getLogger("arena")

# ---------------------------------------------------------------------------
# Phase dispatch table
# ---------------------------------------------------------------------------

PHASE_HANDLERS = {
    Phase.SOLVE: step_solve,
    Phase.EVALUATE: step_evaluate,
    Phase.REVISE: step_revise,
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

    Naming scheme:
    ``{round:02d}-{phase_number}-{phase_name}-{model}-{artifact_type}-{uid}.{ext}``

    Uses model names as identity (vs aliases in agent-committed files).
    *uid* is derived from content (SHA-256 prefix) for deduplication.
    Files already present on disk are not overwritten.
    """
    rnd = state.round

    for alias in state.alias_mapping:
        model = sanitize_filename_component(
            str(state.alias_mapping.get(alias, "unknown"))
        )

        # Determine which solve/revise phase produced the current solutions
        # (solve for round 0, revise for subsequent rounds)
        sol_phase = "solve" if rnd == 0 and state.phase != Phase.EVALUATE else "revise"
        if rnd == 0 and state.phase in (Phase.EVALUATE, Phase.REVISE, Phase.DONE):
            # Round 0: solutions come from solve
            sol_phase = "solve"
        elif rnd > 0:
            sol_phase = "revise"
        sol_phase_num = PHASE_NUMBERS[sol_phase]

        solution = state.solutions.get(alias)
        if solution:
            uid = _content_uid(solution)
            name = f"{rnd:02d}-{sol_phase_num}-{sol_phase}-{model}-solution-{uid}.md"
            _archive_artifact(arena_dir, name, solution)

        analysis = state.analyses.get(alias)
        if analysis:
            uid = _content_uid(analysis)
            name = f"{rnd:02d}-{sol_phase_num}-{sol_phase}-{model}-analysis-{uid}.md"
            _archive_artifact(arena_dir, name, analysis)

        critique = state.critiques.get(alias)
        if critique:
            uid = _content_uid(critique)
            eval_num = PHASE_NUMBERS["evaluate"]
            name = f"{rnd:02d}-{eval_num}-evaluate-{model}-critique-{uid}.md"
            _archive_artifact(arena_dir, name, critique)

        # Archive per-agent verdict
        votes = state.verify_votes.get(alias)
        score = state.verify_scores.get(alias)
        divergences = state.verify_divergences.get(alias, [])
        if votes is not None or score is not None:
            verdict_data: dict = {
                "convergence_score": score,
                "best_solutions": votes or [],
                "divergences": divergences,
            }
            verdict_json = json.dumps(verdict_data, indent=2)
            uid = _content_uid(verdict_json)
            eval_num = PHASE_NUMBERS["evaluate"]
            name = f"{rnd:02d}-{eval_num}-evaluate-{model}-verdict-{uid}.json"
            _archive_artifact(arena_dir, name, verdict_json)


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
    ]

    # Voting results
    if state.verify_scores or state.verify_votes:
        report_lines.append("## Voting Results")
        report_lines.append("")
        for alias in state.alias_mapping:
            model = state.alias_mapping.get(alias, "unknown")
            score = state.verify_scores.get(alias, "N/A")
            votes = state.verify_votes.get(alias, [])
            report_lines.append(
                f"- **{alias}** ({model}): score={score}, voted for {votes}"
            )
        scores = list(state.verify_scores.values())
        final_score = min(scores) if scores else 0
        report_lines.append(f"- **Final score:** {final_score} (min)")
        if state.verify_winner:
            winner_model = state.alias_mapping.get(state.verify_winner, "unknown")
            report_lines.append(f"- **Winner:** {state.verify_winner} ({winner_model})")
        report_lines.extend(["", "---", ""])

    report_lines.append("## Final Solutions")
    report_lines.append("")
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

    # PR URL for the winning branch
    if state.consensus_reached and state.branch_names and state.verify_winner:
        winner_alias = state.verify_winner
        if winner_alias in state.branch_names:
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


def step_once(arena_dir: str = ARENAS_ROOT) -> ArenaState:
    """Execute exactly one phase transition and return the updated state."""
    state_path = os.path.join(arena_dir, "state.yaml")
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


def run_orchestrator(arena_dir: str = ARENAS_ROOT) -> None:
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
