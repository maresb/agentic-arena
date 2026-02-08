"""Main orchestrator loop and report generation.

The orchestrator reads state, dispatches to the appropriate phase function,
and loops until the arena is complete. It is fully stateless: all progress
lives in the state file.
"""

import logging
import os
import uuid

from arena.api import CursorCloudAPI
from arena.phases import step_evaluate, step_revise, step_solve, step_verify
from arena.state import load_state, save_state

logger = logging.getLogger("arena")


def _archive_round(state: dict, arena_dir: str) -> None:
    """Archive the current round's outputs to disk for human review."""
    round_dir = os.path.join(arena_dir, f"round{state['round']}")
    os.makedirs(round_dir, exist_ok=True)

    uid = uuid.uuid4().hex[:8]

    # Archive solutions and analyses
    for alias in state["alias_mapping"]:
        letter = alias.split("_")[1]  # "agent_a" → "a"

        solution = state.get("solutions", {}).get(alias)
        if solution:
            path = os.path.join(round_dir, f"{letter}_solution_{uid}.md")
            with open(path, "w") as f:
                f.write(solution)

        analysis = state.get("analyses", {}).get(alias)
        if analysis:
            path = os.path.join(round_dir, f"{letter}_analysis_{uid}.md")
            with open(path, "w") as f:
                f.write(analysis)

        critique = state.get("critiques", {}).get(alias)
        if critique:
            path = os.path.join(round_dir, f"{letter}_critique_{uid}.md")
            with open(path, "w") as f:
                f.write(critique)

    # Archive verdict if present
    if state.get("final_verdict") and state["phase"] == "done":
        judge_letter = state["judge_history"][-1].split("_")[1]
        path = os.path.join(round_dir, f"verify_{judge_letter}_{uid}.md")
        with open(path, "w") as f:
            f.write(state["final_verdict"])


def generate_final_report(state: dict, arena_dir: str) -> None:
    """Generate a final Markdown report summarizing the arena run."""
    consensus = state.get("consensus_reached", True)
    report_lines = [
        "# Arena Report",
        "",
        f"**Task:** {state['task']}",
        f"**Rounds:** {state['round']}",
        f"**Consensus:** {'Yes' if consensus else 'No'}",
        f"**Alias mapping:** {state['alias_mapping']}",
        "",
        "---",
        "",
        "## Final Verdict",
        "",
        state.get("final_verdict", "N/A"),
        "",
        "---",
        "",
        "## Final Solutions",
        "",
    ]
    for alias, solution in state.get("solutions", {}).items():
        model = state["alias_mapping"].get(alias, "unknown")
        report_lines.append(f"### {alias} ({model})")
        report_lines.append("")
        report_lines.append(solution)
        report_lines.append("")

    if state.get("analyses"):
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## Final Analyses")
        report_lines.append("")
        for alias, analysis in state["analyses"].items():
            model = state["alias_mapping"].get(alias, "unknown")
            report_lines.append(f"### {alias} ({model})")
            report_lines.append("")
            report_lines.append(analysis)
            report_lines.append("")

    report_path = os.path.join(arena_dir, "report.md")
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
    logger.info("Final report written to %s", report_path)


def run_orchestrator(arena_dir: str = "arena") -> None:
    """Main loop: read state, dispatch phase, repeat until done."""
    state_path = os.path.join(arena_dir, "state.json")
    state = load_state(state_path)
    if state is None:
        raise FileNotFoundError(
            f"No state file found at {state_path}. "
            "Use 'python -m arena init' to create one."
        )

    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CURSOR_API_KEY environment variable is not set. "
            "Export your Cursor API key to proceed."
        )
    api = CursorCloudAPI(api_key)

    phase_handlers = {
        "solve": step_solve,
        "evaluate": step_evaluate,
        "revise": step_revise,
        "verify": step_verify,
    }

    while not state["completed"]:
        phase = state["phase"]
        handler = phase_handlers.get(phase)
        if handler is None:
            raise ValueError(f"Unknown phase: {phase}")

        logger.info(
            "=== Round %d | Phase: %s ===",
            state["round"],
            phase,
        )
        handler(state, api)

        # Archive after each phase transition
        _archive_round(state, arena_dir)
        save_state(state, state_path)

    generate_final_report(state, arena_dir)

    consensus = state.get(
        "consensus_reached", state.get("final_verdict") is not None
    )
    print(f"Arena complete. Rounds: {state['round']}.")
    print(f"Verdict: {'Consensus reached' if consensus else 'No consensus (max rounds)'}")
    print(f"Alias mapping: {state['alias_mapping']}")
