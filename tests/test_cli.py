"""Tests for the Typer CLI entry point."""

import os
import tempfile

from typer.testing import CliRunner

from arena.__main__ import app
from arena.state import init_state, load_state, save_state

runner = CliRunner()


class TestInitCommand:
    def test_creates_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task", "Review auth module",
                    "--repo", "owner/repo",
                    "--arena-dir", tmpdir,
                ],
            )
            assert result.exit_code == 0

            state_path = os.path.join(tmpdir, "state.json")
            assert os.path.exists(state_path)

            state = load_state(state_path)
            assert state is not None
            assert state.config.task == "Review auth module"
            assert state.config.repo == "owner/repo"
            assert state.config.max_rounds == 3

    def test_custom_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task", "test",
                    "--repo", "r",
                    "--base-branch", "develop",
                    "--max-rounds", "5",
                    "--arena-dir", tmpdir,
                ],
            )
            assert result.exit_code == 0

            state = load_state(os.path.join(tmpdir, "state.json"))
            assert state is not None
            assert state.config.base_branch == "develop"
            assert state.config.max_rounds == 5

    def test_verify_commands_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task", "test",
                    "--repo", "r",
                    "--verify-commands", "pixi run pytest,pixi run mypy .",
                    "--arena-dir", tmpdir,
                ],
            )
            assert result.exit_code == 0

            state = load_state(os.path.join(tmpdir, "state.json"))
            assert state is not None
            assert state.config.verify_commands == [
                "pixi run pytest",
                "pixi run mypy .",
            ]

    def test_output_contains_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task", "my task",
                    "--repo", "owner/repo",
                    "--arena-dir", tmpdir,
                ],
            )
            assert result.exit_code == 0
            assert "Arena initialized" in result.output
            assert "Alias mapping" in result.output


class TestStatusCommand:
    def test_shows_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task="test", repo="r")
            save_state(state, os.path.join(tmpdir, "state.json"))

            result = runner.invoke(app, ["status", "--arena-dir", tmpdir])
            assert result.exit_code == 0
            assert "Phase: solve" in result.output
            assert "Round: 0" in result.output
            assert "Completed: False" in result.output

    def test_missing_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["status", "--arena-dir", tmpdir])
            assert result.exit_code == 1
            assert "No arena state found" in result.output
