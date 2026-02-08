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

from arena.orchestrator import DEFAULT_ARENA_DIR, generate_final_report, run_orchestrator, step_once  # noqa: E402
from arena.state import load_state, save_state, init_state  # noqa: E402

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
    max_rounds: Annotated[
        int, typer.Option(help="Maximum evaluate-revise-verify rounds")
    ] = 3,
    verify_commands: Annotated[
        str | None,
        typer.Option(help="Comma-separated commands to run during verify"),
    ] = None,
    models: Annotated[
        str | None,
        typer.Option(help="Comma-separated model list (e.g. opus,gpt). Defaults to all."),
    ] = None,
    branch_only: Annotated[
        bool,
        typer.Option(
            "--branch-only",
            help="Omit pasted solutions in prompts; agents must git fetch branches.",
        ),
    ] = False,
    verify_mode: Annotated[
        str,
        typer.Option(help="Verify command mode: 'advisory' (default) or 'gating'"),
    ] = "advisory",
    arena_dir: Annotated[
        str, typer.Option(help="Directory for arena state and outputs")
    ] = DEFAULT_ARENA_DIR,
) -> None:
    """Initialize a new arena run."""
    parsed_commands = verify_commands.split(",") if verify_commands else None
    parsed_models = [m.strip() for m in models.split(",")] if models else None

    state = init_state(
        task=task,
        repo=repo,
        base_branch=base_branch,
        max_rounds=max_rounds,
        verify_commands=parsed_commands,
        models=parsed_models,
        branch_only=branch_only,
        verify_mode=verify_mode,
    )
    state_path = os.path.join(arena_dir, "state.json")
    save_state(state, state_path)

    alias_display = {k: str(v) for k, v in state.alias_mapping.items()}
    typer.echo(f"Arena initialized at {state_path}")
    typer.echo(f"Alias mapping: {alias_display}")
    typer.echo(f"Max rounds: {state.config.max_rounds}")
    if parsed_commands:
        typer.echo(f"Verify commands: {parsed_commands}")
    typer.echo(f"\nRun the arena with: python -m arena run --arena-dir {arena_dir}")


@app.command()
def run(
    arena_dir: Annotated[
        str, typer.Option(help="Directory for arena state and outputs")
    ] = DEFAULT_ARENA_DIR,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose (DEBUG) logging")
    ] = False,
) -> None:
    """Run the arena orchestrator."""
    _setup_logging(arena_dir, verbose=verbose)
    run_orchestrator(arena_dir=arena_dir)


@app.command()
def step(
    arena_dir: Annotated[
        str, typer.Option(help="Directory for arena state and outputs")
    ] = DEFAULT_ARENA_DIR,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose (DEBUG) logging")
    ] = False,
) -> None:
    """Execute a single phase transition (one FSM step)."""
    _setup_logging(arena_dir, verbose=verbose)

    state_path = os.path.join(arena_dir, "state.json")
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
        str, typer.Option(help="Directory for arena state and outputs")
    ] = DEFAULT_ARENA_DIR,
) -> None:
    """Show the current state of the arena."""
    state_path = os.path.join(arena_dir, "state.json")
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

    if state.consensus_reached is not None:
        typer.echo(f"Consensus: {state.consensus_reached}")


if __name__ == "__main__":
    app()
