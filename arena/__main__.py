"""CLI entry point for the Agentic Arena.

Usage:
    python -m arena init        [--task "..."] [--repo owner/repo] [options]
    python -m arena run         [--arena-dir arena]
    python -m arena step        [--arena-dir arena]
    python -m arena status      [--arena-dir arena]
    python -m arena add-comment [--arena-dir arena]
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Annotated

import typer
from dotenv import load_dotenv

load_dotenv()  # Load .env before anything reads CURSOR_API_KEY

from arena.git import default_repo_from_remote  # noqa: E402
from arena.orchestrator import (  # noqa: E402
    PENDING_COMMENTS_FILE,
    arena_number_from_dir,
    latest_arena_dir,
    next_arena_dir,
    reopen_arena,
    run_orchestrator,
    step_once,
)
from arena.state import (  # noqa: E402
    TASK_PLACEHOLDER,
    ProgressStatus,
    init_state,
    load_state,
    save_state,
)

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
    task: Annotated[
        str,
        typer.Option(
            help="Task description for the agents to solve. "
            f"Defaults to '{TASK_PLACEHOLDER}'."
        ),
    ] = TASK_PLACEHOLDER,
    repo: Annotated[
        str | None,
        typer.Option(
            help="GitHub repository (owner/repo format). "
            "Defaults to the 'origin' remote of the current git repo."
        ),
    ] = None,
    base_branch: Annotated[str, typer.Option(help="Base branch to work from")] = "main",
    max_rounds: Annotated[
        int, typer.Option(help="Maximum generate-evaluate rounds")
    ] = 3,
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

    When ``--repo`` is omitted, the ``origin`` remote URL of the
    current git repository is used (supports HTTPS and SSH formats).
    """
    if repo is None:
        repo = default_repo_from_remote()
        if repo is None:
            typer.echo(
                "Could not detect a GitHub remote. "
                "Please specify --repo owner/repo explicitly."
            )
            raise typer.Exit(code=1)
        typer.echo(f"Detected repo from origin remote: {repo}")
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

    state_path = os.path.join(arena_dir, "state.yaml")
    pre_state = load_state(state_path)
    if pre_state is not None and pre_state.config.task == TASK_PLACEHOLDER:
        typer.echo(
            f"Task is still set to the placeholder ({TASK_PLACEHOLDER!r}).\n"
            "Please edit state.yaml to describe the actual task before running."
        )
        raise typer.Exit(code=1)

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
    if before.config.task == TASK_PLACEHOLDER:
        typer.echo(
            f"Task is still set to the placeholder ({TASK_PLACEHOLDER!r}).\n"
            "Please edit state.yaml to describe the actual task before stepping."
        )
        raise typer.Exit(code=1)
    if before.completed:
        typer.echo("Arena is already completed. Nothing to do.")
        raise typer.Exit(code=0)

    before_phase = before.phase
    before_round = before.round

    state = step_once(arena_dir=arena_dir)

    typer.echo(f"{before_phase} -> {state.phase} (round {before_round})")
    if state.completed:
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


@app.command(name="add-comment")
def add_comment(
    arena_dir: Annotated[
        str | None, typer.Option(help="Directory for arena state and outputs")
    ] = None,
    message: Annotated[
        str | None,
        typer.Option("--message", "-m", help="Comment text (skips interactive prompt)"),
    ] = None,
    file: Annotated[
        str | None,
        typer.Option("--file", "-f", help="Read comment text from a file path"),
    ] = None,
    immediate: Annotated[
        bool,
        typer.Option(
            "--immediate", help="Deliver immediately (only when agents are idle)"
        ),
    ] = False,
    queue: Annotated[
        bool,
        typer.Option("--queue", help="Queue for delivery at next phase start"),
    ] = False,
    no_wrap: Annotated[
        bool,
        typer.Option(
            "--no-wrap",
            help="Send message as-is without operator context framing",
        ),
    ] = False,
    targets: Annotated[
        str | None,
        typer.Option(
            help="Comma-separated agent aliases to target (default: all agents)"
        ),
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose (DEBUG) logging")
    ] = False,
) -> None:
    """Inject a message into agent conversations.

    Sends an operator comment to one or more agents. When agents are idle
    the comment can be delivered immediately; otherwise it is queued in a
    sidecar file and delivered at the start of the next phase.

    Interactive mode (no flags) walks through delivery mode, message text,
    framing, and target selection step by step.
    """
    arena_dir = _resolve_arena_dir(arena_dir)
    state_path = os.path.join(arena_dir, "state.yaml")
    state = load_state(state_path)
    if state is None:
        typer.echo(f"No arena state found at {state_path}")
        raise typer.Exit(code=1)

    if not state.agent_ids:
        typer.echo("No agents have been launched yet. Run at least one step first.")
        raise typer.Exit(code=1)

    # Interactive mode: neither --message nor --file provided
    _is_interactive = message is None and file is None

    # ── Handle completed arena ──
    if state.completed:
        if _is_interactive:
            typer.echo(
                f"\nArena is completed (round {state.round}, "
                f"phase: {state.phase.value})."
            )
            reopen = typer.confirm("Reopen arena for another round?", default=True)
            if not reopen:
                typer.echo("Aborting.")
                raise typer.Exit(code=0)
            reopen_arena(state)
            save_state(state, state_path)
            typer.echo(
                f"Arena reopened — now at round {state.round}, "
                f"phase: {state.phase.value}"
            )
        else:
            typer.echo(
                "Arena is completed. Run interactively (without --message / "
                "--file) to reopen, or edit state.yaml manually."
            )
            raise typer.Exit(code=1)

    # ── Detect whether a step is in progress ──
    step_in_progress = any(
        v == ProgressStatus.SENT for v in state.phase_progress.values()
    )

    # ── Resolve target aliases ──
    if targets is not None:
        target_list = [t.strip() for t in targets.split(",") if t.strip()]
        for t in target_list:
            if t not in state.alias_mapping:
                typer.echo(f"Unknown agent alias: {t}")
                typer.echo(f"Valid aliases: {', '.join(state.alias_mapping)}")
                raise typer.Exit(code=1)
    else:
        # Interactive or default: all agents
        if _is_interactive:
            # Interactive target selection
            aliases = list(state.alias_mapping.keys())
            typer.echo("\nAvailable agents:")
            for i, alias in enumerate(aliases, 1):
                model = state.alias_mapping.get(alias, "unknown")
                typer.echo(f"  {i}. {alias} ({model})")
            typer.echo("  0. All agents")

            choice = typer.prompt(
                "Target agents (0 for all, or comma-separated numbers)",
                default="0",
            )
            if choice.strip() == "0":
                target_list = aliases
            else:
                indices = [int(x.strip()) for x in choice.split(",") if x.strip()]
                target_list = []
                for idx in indices:
                    if 1 <= idx <= len(aliases):
                        target_list.append(aliases[idx - 1])
                    else:
                        typer.echo(f"Invalid selection: {idx}")
                        raise typer.Exit(code=1)
        else:
            target_list = list(state.alias_mapping.keys())

    # ── Resolve delivery mode ──
    if immediate and queue:
        typer.echo("Cannot specify both --immediate and --queue")
        raise typer.Exit(code=1)

    if not immediate and not queue:
        # Interactive mode
        if step_in_progress:
            typer.echo(
                "\nA step is currently in progress — only queued delivery is available."
            )
            delivery = "queue"
        else:
            import click

            delivery = typer.prompt(
                "\nDelivery mode",
                type=click.Choice(["immediate", "queue"]),
                default="immediate",
            )
    elif immediate:
        if step_in_progress:
            typer.echo(
                "Cannot deliver immediately — a step is in progress. "
                "Use --queue instead."
            )
            raise typer.Exit(code=1)
        delivery = "immediate"
    else:
        delivery = "queue"

    # ── Read file content (if any) ──
    file_content: str | None = None
    if file is not None:
        file_path = os.path.expanduser(file)
        if not os.path.isfile(file_path):
            typer.echo(f"File not found: {file_path}")
            raise typer.Exit(code=1)
        with open(file_path) as fh:
            file_content = fh.read()
        if not file_content.strip():
            typer.echo(f"File is empty: {file_path}")
            raise typer.Exit(code=1)

    # ── Get message text ──
    if message is None and file_content is None:
        # Fully interactive: prompt for message
        typer.echo("\nEnter your message (end with an empty line):")
        lines: list[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line == "":
                break
            lines.append(line)
        message = "\n".join(lines)
        if not message.strip():
            typer.echo("Empty message — aborting.")
            raise typer.Exit(code=1)
    elif message is not None and file_content is not None:
        # Both --message and --file: preamble + file contents
        message = message + "\n\n" + file_content
    elif file_content is not None:
        # --file only
        message = file_content

    # ── Resolve wrapping ──
    # In non-interactive mode (--message flag), default to wrapping unless
    # --no-wrap is set.  In interactive mode, ask.
    if no_wrap:
        wrap = False
    elif _is_interactive:
        wrap = typer.confirm(
            "\nWrap message with operator context framing?", default=True
        )
    else:
        wrap = True

    # At this point message is guaranteed to be a non-empty string
    assert message is not None

    # ── Execute ──
    target_display = ", ".join(target_list)

    if delivery == "immediate":
        _setup_logging(arena_dir, verbose=verbose)
        from arena.orchestrator import _make_api  # noqa: E402

        api = _make_api()

        from arena.api import wait_for_followup  # noqa: E402
        from arena.orchestrator import OPERATOR_WRAP_TEMPLATE  # noqa: E402
        from arena.phases import (  # noqa: E402
            _save_conversation,
            _update_token_usage,
        )

        final_message = (
            OPERATOR_WRAP_TEMPLATE.format(message=message) if wrap else message
        )

        for alias in target_list:
            agent_id = state.agent_ids.get(alias)
            if not agent_id:
                typer.echo(f"  Skipping {alias} — no agent_id")
                continue
            typer.echo(f"  Sending to {alias}...")
            prev_count = len(api.get_conversation(agent_id))
            api.followup(agent_id=agent_id, prompt=final_message)
            wait_for_followup(api, agent_id, prev_count)

            conversation = api.get_conversation(agent_id)
            _update_token_usage(state, alias, conversation)
            _save_conversation(state, state_path, alias, conversation)

        save_state(state, state_path)
        typer.echo(f"\nDelivered immediately to: {target_display}")
    else:
        # Queue to sidecar file
        sidecar_path = os.path.join(arena_dir, PENDING_COMMENTS_FILE)
        existing: list[dict] = []
        if os.path.exists(sidecar_path):
            try:
                with open(sidecar_path) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, ValueError):
                existing = []

        existing.append(
            {
                "message": message,
                "wrapped": wrap,
                "targets": target_list,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        with open(sidecar_path, "w") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

        typer.echo(
            f"\nQueued comment for: {target_display}\n"
            f"Will be delivered at the start of the next phase.\n"
            f"File: {sidecar_path}"
        )


if __name__ == "__main__":
    app()
