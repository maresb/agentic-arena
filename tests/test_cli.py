"""Tests for the Typer CLI entry point."""

import json
import os
import tempfile
from unittest.mock import patch

from typer.testing import CliRunner

from arena.__main__ import app
from arena.orchestrator import PENDING_COMMENTS_FILE
from arena.state import TASK_PLACEHOLDER, init_state, load_state, save_state

runner = CliRunner()


class TestInitCommand:
    def test_creates_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task",
                    "Review auth module",
                    "--repo",
                    "owner/repo",
                    "--arena-dir",
                    tmpdir,
                ],
            )
            assert result.exit_code == 0

            state_path = os.path.join(tmpdir, "state.yaml")
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
                    "--task",
                    "test",
                    "--repo",
                    "r",
                    "--base-branch",
                    "develop",
                    "--max-rounds",
                    "5",
                    "--arena-dir",
                    tmpdir,
                ],
            )
            assert result.exit_code == 0

            state = load_state(os.path.join(tmpdir, "state.yaml"))
            assert state is not None
            assert state.config.base_branch == "develop"
            assert state.config.max_rounds == 5

    def test_verify_commands_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task",
                    "test",
                    "--repo",
                    "r",
                    "--verify-commands",
                    "pixi run pytest,pixi run mypy .",
                    "--arena-dir",
                    tmpdir,
                ],
            )
            assert result.exit_code == 0

            state = load_state(os.path.join(tmpdir, "state.yaml"))
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
                    "--task",
                    "my task",
                    "--repo",
                    "owner/repo",
                    "--arena-dir",
                    tmpdir,
                ],
            )
            assert result.exit_code == 0
            assert "Arena initialized" in result.output
            assert "Alias mapping" in result.output


class TestInitModelsFlag:
    def test_custom_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task",
                    "test",
                    "--repo",
                    "r",
                    "--models",
                    "opus,gpt",
                    "--arena-dir",
                    tmpdir,
                ],
            )
            assert result.exit_code == 0
            state = load_state(os.path.join(tmpdir, "state.yaml"))
            assert state is not None
            assert len(state.alias_mapping) == 2

    def test_verify_mode_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task",
                    "test",
                    "--repo",
                    "r",
                    "--verify-mode",
                    "gating",
                    "--arena-dir",
                    tmpdir,
                ],
            )
            assert result.exit_code == 0
            state = load_state(os.path.join(tmpdir, "state.yaml"))
            assert state is not None
            assert state.config.verify_mode == "gating"

    def test_arena_number_from_dir(self) -> None:
        """Arena number is derived from the directory name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            arena_dir = os.path.join(tmpdir, "0042")
            os.makedirs(arena_dir)
            result = runner.invoke(
                app,
                [
                    "init",
                    "--task",
                    "test",
                    "--repo",
                    "r",
                    "--arena-dir",
                    arena_dir,
                ],
            )
            assert result.exit_code == 0
            state = load_state(os.path.join(arena_dir, "state.yaml"))
            assert state is not None
            assert state.config.arena_number == 42


class TestInitDefaults:
    @patch("arena.__main__.default_repo_from_remote", return_value="detected/repo")
    def test_defaults_task_placeholder(self, _mock_remote: object) -> None:
        """init with no --task defaults to the placeholder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                ["init", "--arena-dir", tmpdir],
            )
            assert result.exit_code == 0
            state = load_state(os.path.join(tmpdir, "state.yaml"))
            assert state is not None
            assert state.config.task == TASK_PLACEHOLDER

    @patch("arena.__main__.default_repo_from_remote", return_value="detected/repo")
    def test_defaults_repo_from_remote(self, _mock_remote: object) -> None:
        """init with no --repo detects the origin remote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                ["init", "--task", "my task", "--arena-dir", tmpdir],
            )
            assert result.exit_code == 0
            assert "Detected repo from origin remote" in result.output
            state = load_state(os.path.join(tmpdir, "state.yaml"))
            assert state is not None
            assert state.config.repo == "detected/repo"

    @patch("arena.__main__.default_repo_from_remote", return_value=None)
    def test_fails_when_no_remote_and_no_repo(self, _mock_remote: object) -> None:
        """init fails gracefully when no remote is detected and --repo is omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app,
                ["init", "--task", "my task", "--arena-dir", tmpdir],
            )
            assert result.exit_code == 1
            assert "Could not detect" in result.output


class TestStepCommand:
    def test_missing_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["step", "--arena-dir", tmpdir])
            assert result.exit_code == 1
            assert "No arena state found" in result.output

    def test_already_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task="test", repo="r")
            state.completed = True
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            result = runner.invoke(app, ["step", "--arena-dir", tmpdir])
            assert result.exit_code == 0
            assert "already completed" in result.output

    def test_balks_at_placeholder_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task=TASK_PLACEHOLDER, repo="r")
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            result = runner.invoke(app, ["step", "--arena-dir", tmpdir])
            assert result.exit_code == 1
            assert "placeholder" in result.output


class TestRunCommand:
    def test_balks_at_placeholder_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task=TASK_PLACEHOLDER, repo="r")
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            result = runner.invoke(app, ["run", "--arena-dir", tmpdir])
            assert result.exit_code == 1
            assert "placeholder" in result.output


class TestStatusCommand:
    def test_shows_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task="test", repo="r")
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            result = runner.invoke(app, ["status", "--arena-dir", tmpdir])
            assert result.exit_code == 0
            assert "Phase: generate" in result.output
            assert "Round: 0" in result.output
            assert "Completed: False" in result.output

    def test_missing_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["status", "--arena-dir", tmpdir])
            assert result.exit_code == 1
            assert "No arena state found" in result.output

    def test_shows_voting_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task="test", repo="r")
            state.verify_votes = {"agent_a": ["agent_b"]}
            state.verify_scores = {"agent_a": 8}
            state.verify_winner = "agent_b"
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            result = runner.invoke(app, ["status", "--arena-dir", tmpdir])
            assert result.exit_code == 0
            assert "Voting" in result.output
            assert "score=8" in result.output
            assert "Winner" in result.output


class TestAddCommentCommand:
    def _make_state_with_agents(self, tmpdir: str) -> None:
        """Create a state with agent IDs so add-comment can proceed."""
        state = init_state(task="test", repo="r")
        for i, alias in enumerate(state.alias_mapping):
            state.agent_ids[alias] = f"agent-{i}"
        save_state(state, os.path.join(tmpdir, "state.yaml"))

    def test_no_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app, ["add-comment", "--arena-dir", tmpdir, "-m", "hi"]
            )
            assert result.exit_code == 1
            assert "No arena state found" in result.output

    def test_no_agents_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task="test", repo="r")
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            result = runner.invoke(
                app, ["add-comment", "--arena-dir", tmpdir, "-m", "hi"]
            )
            assert result.exit_code == 1
            assert "No agents" in result.output

    def test_queue_creates_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_state_with_agents(tmpdir)

            result = runner.invoke(
                app,
                [
                    "add-comment",
                    "--arena-dir",
                    tmpdir,
                    "-m",
                    "Please focus on edge cases",
                    "--queue",
                ],
            )
            assert result.exit_code == 0
            assert "Queued" in result.output

            sidecar = os.path.join(tmpdir, PENDING_COMMENTS_FILE)
            assert os.path.exists(sidecar)
            with open(sidecar) as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]["message"] == "Please focus on edge cases"
            assert data[0]["wrapped"] is True
            assert len(data[0]["targets"]) == 3

    def test_queue_no_wrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_state_with_agents(tmpdir)

            result = runner.invoke(
                app,
                [
                    "add-comment",
                    "--arena-dir",
                    tmpdir,
                    "-m",
                    "raw message",
                    "--queue",
                    "--no-wrap",
                ],
            )
            assert result.exit_code == 0

            sidecar = os.path.join(tmpdir, PENDING_COMMENTS_FILE)
            with open(sidecar) as f:
                data = json.load(f)
            assert data[0]["wrapped"] is False

    def test_queue_specific_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_state_with_agents(tmpdir)

            result = runner.invoke(
                app,
                [
                    "add-comment",
                    "--arena-dir",
                    tmpdir,
                    "-m",
                    "msg",
                    "--queue",
                    "--targets",
                    "agent_a",
                ],
            )
            assert result.exit_code == 0

            sidecar = os.path.join(tmpdir, PENDING_COMMENTS_FILE)
            with open(sidecar) as f:
                data = json.load(f)
            assert data[0]["targets"] == ["agent_a"]

    def test_queue_invalid_target_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_state_with_agents(tmpdir)

            result = runner.invoke(
                app,
                [
                    "add-comment",
                    "--arena-dir",
                    tmpdir,
                    "-m",
                    "msg",
                    "--queue",
                    "--targets",
                    "nonexistent",
                ],
            )
            assert result.exit_code == 1
            assert "Unknown agent alias" in result.output

    def test_queue_appends_to_existing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_state_with_agents(tmpdir)

            # Write an existing queued comment
            sidecar = os.path.join(tmpdir, PENDING_COMMENTS_FILE)
            with open(sidecar, "w") as f:
                json.dump(
                    [{"message": "first", "wrapped": True, "targets": ["agent_a"]}], f
                )

            result = runner.invoke(
                app,
                [
                    "add-comment",
                    "--arena-dir",
                    tmpdir,
                    "-m",
                    "second",
                    "--queue",
                ],
            )
            assert result.exit_code == 0

            with open(sidecar) as f:
                data = json.load(f)
            assert len(data) == 2
            assert data[0]["message"] == "first"
            assert data[1]["message"] == "second"

    def test_immediate_and_queue_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_state_with_agents(tmpdir)

            result = runner.invoke(
                app,
                [
                    "add-comment",
                    "--arena-dir",
                    tmpdir,
                    "-m",
                    "msg",
                    "--immediate",
                    "--queue",
                ],
            )
            assert result.exit_code == 1
            assert "Cannot specify both" in result.output
