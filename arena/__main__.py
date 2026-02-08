"""CLI entry point for the Agentic Arena.

Usage:
    python -m arena init --task "..." --repo owner/repo [options]
    python -m arena run  [--arena-dir arena]
    python -m arena status [--arena-dir arena]
"""

import argparse
import json
import logging
import sys

from arena.orchestrator import run_orchestrator
from arena.state import init_state, load_state, save_state


def setup_logging(arena_dir: str, verbose: bool = False) -> None:
    """Configure logging to both console and file."""
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Root logger
    root = logging.getLogger("arena")
    root.setLevel(log_level)

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter(log_format))
    root.addHandler(console)

    # File handler
    import os

    os.makedirs(arena_dir, exist_ok=True)
    file_handler = logging.FileHandler(
        os.path.join(arena_dir, "orchestrator.log"),
        mode="a",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    root.addHandler(file_handler)


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize a new arena run."""
    verify_commands = args.verify_commands.split(",") if args.verify_commands else None

    state = init_state(
        task=args.task,
        repo=args.repo,
        base_branch=args.base_branch,
        max_rounds=args.max_rounds,
        verify_commands=verify_commands,
    )
    state_path = f"{args.arena_dir}/state.json"
    save_state(state, state_path)

    print(f"Arena initialized at {state_path}")
    print(f"Alias mapping: {state['alias_mapping']}")
    print(f"Max rounds: {state['max_rounds']}")
    if verify_commands:
        print(f"Verify commands: {verify_commands}")
    print(f"\nRun the arena with: python -m arena run --arena-dir {args.arena_dir}")


def cmd_run(args: argparse.Namespace) -> None:
    """Run the arena orchestrator."""
    setup_logging(args.arena_dir, verbose=args.verbose)
    run_orchestrator(arena_dir=args.arena_dir)


def cmd_status(args: argparse.Namespace) -> None:
    """Show the current state of the arena."""
    state = load_state(f"{args.arena_dir}/state.json")
    if state is None:
        print(f"No arena state found at {args.arena_dir}/state.json")
        sys.exit(1)

    print(f"Phase: {state['phase']}")
    print(f"Round: {state['round']} / {state['max_rounds']}")
    print(f"Completed: {state['completed']}")
    print(f"Alias mapping: {state['alias_mapping']}")
    print(f"Agent IDs: {json.dumps(state.get('agent_ids', {}), indent=2)}")

    progress = state.get("phase_progress", {})
    print(f"Phase progress: {json.dumps(progress, indent=2)}")

    if state.get("consensus_reached") is not None:
        print(f"Consensus: {state['consensus_reached']}")


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = argparse.ArgumentParser(
        prog="arena",
        description="Agentic Arena — Multi-model consensus via Cursor Cloud Agents",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- init ---
    p_init = subparsers.add_parser("init", help="Initialize a new arena run")
    p_init.add_argument(
        "--task",
        required=True,
        help="Task description for the agents to solve",
    )
    p_init.add_argument(
        "--repo",
        required=True,
        help="GitHub repository (owner/repo format)",
    )
    p_init.add_argument(
        "--base-branch",
        default="main",
        help="Base branch to work from (default: main)",
    )
    p_init.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Maximum evaluate→revise→verify rounds (default: 3)",
    )
    p_init.add_argument(
        "--verify-commands",
        default=None,
        help="Comma-separated commands to run during verify (e.g. 'pixi run pytest,pixi run mypy .')",
    )
    p_init.add_argument(
        "--arena-dir",
        default="arena",
        help="Directory for arena state and outputs (default: arena)",
    )
    p_init.set_defaults(func=cmd_init)

    # --- run ---
    p_run = subparsers.add_parser("run", help="Run the arena orchestrator")
    p_run.add_argument(
        "--arena-dir",
        default="arena",
        help="Directory for arena state and outputs (default: arena)",
    )
    p_run.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    p_run.set_defaults(func=cmd_run)

    # --- status ---
    p_status = subparsers.add_parser("status", help="Show current arena status")
    p_status.add_argument(
        "--arena-dir",
        default="arena",
        help="Directory for arena state and outputs (default: arena)",
    )
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
