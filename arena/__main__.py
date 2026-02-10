"""CLI entry point for the Agentic Arena.

Usage:
    python -m arena init   --task "..." --repo owner/repo [options]
    python -m arena run    [--arena-dir arena]
    python -m arena step   [--arena-dir arena]
    python -m arena status [--arena-dir arena]
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Annotated

import typer
from dotenv import load_dotenv

load_dotenv()  # Load .env before anything reads CURSOR_API_KEY

from arena.orchestrator import (  # noqa: E402
    arena_number_from_dir,
    generate_final_report,
    latest_arena_dir,
    next_arena_dir,
    run_orchestrator,
    step_once,
)
from arena.state import init_state, load_state, save_state  # noqa: E402

app = typer.Typer(
    name="arena",
    help="Agentic Arena — Multi-model consensus via Cursor Cloud Agents.",
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(arena_dir: str, *, verbose: bool = False) -> None:
    """Configure logging to both console and file."""
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    root = logging.getLogger("arena")
    root.setLevel(log_level)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter(log_format))
    root.addHandler(console)

    os.makedirs(arena_dir, exist_ok=True)
    file_handler = logging.FileHandler(
        os.path.join(arena_dir, "orchestrator.log"),
        mode="a",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    root.addHandler(file_handler)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    task: Annotated[str, typer.Option(help="Task description for the agents to solve")],
    repo: Annotated[str, typer.Option(help="GitHub repository (owner/repo format)")],
    base_branch: Annotated[str, typer.Option(help="Base branch to work from")] = "main",
    max_rounds: Annotated[int, typer.Option(help="Maximum evaluate-revise rounds")] = 3,
    verify_commands: Annotated[
        str | None,
        typer.Option(help="Comma-separated commands to run during verify"),
    ] = None,
    models: Annotated[
        str | None,
        typer.Option(
            help="Comma-separated model list (e.g. opus,gpt). Defaults to all."
        ),
    ] = None,
    verify_mode: Annotated[
        str,
        typer.Option(
            help="Verify command mode: 'advisory' (default) or 'gating'",
            case_sensitive=False,
        ),
    ] = "advisory",
    arena_dir: Annotated[
        str | None, typer.Option(help="Directory for arena state and outputs")
    ] = None,
) -> None:
    """Initialize a new arena run.

    When ``--arena-dir`` is omitted, a new sequentially-numbered
    directory under ``arenas/`` is created automatically.
    """
    if arena_dir is None:
        arena_dir = next_arena_dir()
    parsed_commands = verify_commands.split(",") if verify_commands else None
    parsed_models = (
        [m.strip() for m in models.split(",") if m.strip()] if models else None
    )
    if models and not parsed_models:
        raise typer.BadParameter("--models must contain at least one model name")

    anum = arena_number_from_dir(arena_dir)

    state = init_state(
        task=task,
        repo=repo,
        base_branch=base_branch,
        max_rounds=max_rounds,
        verify_commands=parsed_commands,
        models=parsed_models,
        verify_mode=verify_mode,
        arena_number=anum,
    )
    state_path = os.path.join(arena_dir, "state.yaml")
    save_state(state, state_path)

    alias_display = {k: str(v) for k, v in state.alias_mapping.items()}
    typer.echo(f"Arena initialized at {state_path}")
    typer.echo(f"Alias mapping: {alias_display}")
    typer.echo(f"Max rounds: {state.config.max_rounds}")
    if parsed_commands:
        typer.echo(f"Verify commands: {parsed_commands}")
    typer.echo(f"\nRun the arena with: python -m arena run --arena-dir {arena_dir}")


def _resolve_arena_dir(arena_dir: str | None) -> str:
    """Resolve *arena_dir*, defaulting to the latest numbered directory."""
    if arena_dir is not None:
        return arena_dir
    resolved = latest_arena_dir()
    if resolved is None:
        typer.echo("No arena runs found. Use 'python -m arena init' first.")
        raise typer.Exit(code=1)
    return resolved


@app.command()
def run(
    arena_dir: Annotated[
        str | None, typer.Option(help="Directory for arena state and outputs")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose (DEBUG) logging")
    ] = False,
) -> None:
    """Run the arena orchestrator.

    When ``--arena-dir`` is omitted, uses the latest arena directory.
    """
    arena_dir = _resolve_arena_dir(arena_dir)
    _setup_logging(arena_dir, verbose=verbose)
    run_orchestrator(arena_dir=arena_dir)


@app.command()
def step(
    arena_dir: Annotated[
        str | None, typer.Option(help="Directory for arena state and outputs")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose (DEBUG) logging")
    ] = False,
) -> None:
    """Execute a single phase transition (one FSM step).

    When ``--arena-dir`` is omitted, uses the latest arena directory.
    """
    arena_dir = _resolve_arena_dir(arena_dir)
    _setup_logging(arena_dir, verbose=verbose)

    state_path = os.path.join(arena_dir, "state.yaml")
    before = load_state(state_path)
    if before is None:
        typer.echo(f"No arena state found at {state_path}")
        raise typer.Exit(code=1)
    if before.completed:
        typer.echo("Arena is already completed. Nothing to do.")
        raise typer.Exit(code=0)

    before_phase = before.phase
    before_round = before.round

    state = step_once(arena_dir=arena_dir)

    typer.echo(f"{before_phase} -> {state.phase} (round {before_round})")
    if state.completed:
        generate_final_report(state, arena_dir)
        consensus = state.consensus_reached
        typer.echo(
            f"Arena complete: {'consensus reached' if consensus else 'no consensus (max rounds)'}"
        )


@app.command()
def status(
    arena_dir: Annotated[
        str | None, typer.Option(help="Directory for arena state and outputs")
    ] = None,
) -> None:
    """Show the current state of the arena.

    When ``--arena-dir`` is omitted, uses the latest arena directory.
    """
    arena_dir = _resolve_arena_dir(arena_dir)
    state_path = os.path.join(arena_dir, "state.yaml")
    state = load_state(state_path)
    if state is None:
        typer.echo(f"No arena state found at {state_path}")
        raise typer.Exit(code=1)

    alias_display = {k: str(v) for k, v in state.alias_mapping.items()}
    typer.echo(f"Phase: {state.phase}")
    typer.echo(f"Round: {state.round} / {state.config.max_rounds}")
    typer.echo(f"Completed: {state.completed}")
    typer.echo(f"Alias mapping: {alias_display}")
    typer.echo(f"Agent IDs: {state.agent_ids}")

    progress_display = {k: str(v) for k, v in state.phase_progress.items()}
    typer.echo(f"Phase progress: {progress_display}")

    if state.branch_names:
        typer.echo(f"Branch names: {state.branch_names}")

    if state.agent_timing:
        typer.echo("Agent timing:")
        for alias, phases in sorted(state.agent_timing.items()):
            model = state.alias_mapping.get(alias, "unknown")
            for phase_name, times in sorted(phases.items()):
                start = times.get("start")
                end = times.get("end")
                if start and end:
                    duration = end - start
                    typer.echo(f"  {alias} ({model}) {phase_name}: {duration:.1f}s")
                elif start:
                    typer.echo(f"  {alias} ({model}) {phase_name}: in progress")

    if state.agent_metadata:
        typer.echo("Agent metadata:")
        for alias, meta in sorted(state.agent_metadata.items()):
            model = state.alias_mapping.get(alias, "unknown")
            parts = [f"{k}={v}" for k, v in meta.items()]
            typer.echo(f"  {alias} ({model}): {', '.join(parts)}")

    if state.verify_scores or state.verify_votes:
        typer.echo("Voting:")
        for alias in state.alias_mapping:
            model = state.alias_mapping.get(alias, "unknown")
            score = state.verify_scores.get(alias, "N/A")
            votes = state.verify_votes.get(alias, [])
            typer.echo(f"  {alias} ({model}): score={score}, voted for {votes}")
        scores = list(state.verify_scores.values())
        if scores:
            typer.echo(f"  Final score: {min(scores)} (min)")
        if state.verify_winner:
            typer.echo(f"  Winner: {state.verify_winner}")

    if state.consensus_reached is not None:
        typer.echo(f"Consensus: {state.consensus_reached}")


if __name__ == "__main__":
    app()
