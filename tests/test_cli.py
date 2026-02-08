"""Tests for the CLI entry point."""

import json
import os
import tempfile

from arena.__main__ import cmd_init, cmd_status


class MockNamespace:
    """Minimal argparse.Namespace replacement for testing."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestCmdInit:
    def test_creates_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = MockNamespace(
                task="Review auth module",
                repo="owner/repo",
                base_branch="main",
                max_rounds=2,
                verify_commands=None,
                arena_dir=tmpdir,
            )
            cmd_init(args)

            state_path = os.path.join(tmpdir, "state.json")
            assert os.path.exists(state_path)

            with open(state_path) as f:
                state = json.load(f)

            assert state["task"] == "Review auth module"
            assert state["repo"] == "owner/repo"
            assert state["max_rounds"] == 2

    def test_verify_commands_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = MockNamespace(
                task="test",
                repo="r",
                base_branch="main",
                max_rounds=3,
                verify_commands="pixi run pytest,pixi run mypy .",
                arena_dir=tmpdir,
            )
            cmd_init(args)

            with open(os.path.join(tmpdir, "state.json")) as f:
                state = json.load(f)

            assert state["verify_commands"] == [
                "pixi run pytest",
                "pixi run mypy .",
            ]


class TestCmdStatus:
    def test_shows_status(self, capsys: object) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a state file first
            from arena.state import init_state, save_state

            state = init_state(task="test", repo="r")
            save_state(state, os.path.join(tmpdir, "state.json"))

            args = MockNamespace(arena_dir=tmpdir)
            cmd_status(args)
            # If we get here without error, the status command works
