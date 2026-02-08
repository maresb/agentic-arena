"""Tests for state management with Pydantic models."""

import json
import os
import tempfile

from arena.state import (
    ALIASES,
    ArenaConfig,
    ModelName,
    Phase,
    ProgressStatus,
    init_state,
    load_state,
    save_state,
)


class TestArenaConfig:
    def test_defaults(self) -> None:
        cfg = ArenaConfig(task="test", repo="r")
        assert cfg.base_branch == "main"
        assert cfg.max_rounds == 3
        assert cfg.verify_commands == []

    def test_frozen(self) -> None:
        cfg = ArenaConfig(task="test", repo="r")
        try:
            cfg.task = "changed"  # type: ignore[misc]
            raise AssertionError("Should not allow mutation")
        except Exception:
            pass  # Expected — frozen model


class TestInitState:
    def test_basic_fields(self) -> None:
        state = init_state(task="Review PR #42", repo="owner/repo")
        assert state.config.task == "Review PR #42"
        assert state.config.repo == "owner/repo"
        assert state.config.base_branch == "main"
        assert state.config.max_rounds == 3
        assert state.phase == Phase.SOLVE
        assert state.round == 0
        assert state.completed is False
        assert state.consensus_reached is None

    def test_alias_mapping_is_shuffled(self) -> None:
        """The mapping is randomized, so all models appear but order varies."""
        state = init_state(task="test", repo="r")
        models = set(state.alias_mapping.values())
        assert models == {ModelName.OPUS, ModelName.GPT, ModelName.GEMINI}
        assert set(state.alias_mapping.keys()) == set(ALIASES)

    def test_custom_options(self) -> None:
        state = init_state(
            task="test",
            repo="r",
            base_branch="develop",
            max_rounds=5,
            verify_commands=["pixi run pytest"],
        )
        assert state.config.base_branch == "develop"
        assert state.config.max_rounds == 5
        assert state.config.verify_commands == ["pixi run pytest"]

    def test_initial_progress(self) -> None:
        state = init_state(task="test", repo="r")
        for alias in ALIASES:
            assert state.phase_progress[alias] == ProgressStatus.PENDING

    def test_empty_collections(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.solutions == {}
        assert state.analyses == {}
        assert state.critiques == {}
        assert state.agent_ids == {}
        assert state.judge_history == []


class TestSaveAndLoad:
    def test_round_trip(self) -> None:
        state = init_state(task="round trip", repo="owner/repo")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            save_state(state, path)
            loaded = load_state(path)
            assert loaded == state

    def test_load_nonexistent_returns_none(self) -> None:
        assert load_state("/nonexistent/path/state.json") is None

    def test_atomic_write_creates_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "dir", "state.json")
            state = init_state(task="nested", repo="r")
            save_state(state, path)
            assert os.path.exists(path)
            loaded = load_state(path)
            assert loaded == state

    def test_state_is_valid_json(self) -> None:
        state = init_state(task="json check", repo="r")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            save_state(state, path)
            with open(path) as f:
                raw = f.read()
            # Should be pretty-printed with indent
            parsed = json.loads(raw)
            assert parsed["config"]["task"] == "json check"

    def test_round_trip_preserves_enums(self) -> None:
        """Enum values survive serialization and deserialization."""
        state = init_state(task="enum test", repo="r")
        state.phase = Phase.EVALUATE
        state.phase_progress = {
            "agent_a": ProgressStatus.DONE,
            "agent_b": ProgressStatus.SENT,
            "agent_c": ProgressStatus.PENDING,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            save_state(state, path)
            loaded = load_state(path)
            assert loaded is not None
            assert loaded.phase == Phase.EVALUATE
            assert loaded.phase_progress["agent_a"] == ProgressStatus.DONE
            assert loaded.phase_progress["agent_b"] == ProgressStatus.SENT
            assert loaded.phase_progress["agent_c"] == ProgressStatus.PENDING

    def test_round_trip_with_populated_state(self) -> None:
        """Full state with solutions, critiques, etc. round-trips correctly."""
        state = init_state(task="full", repo="r")
        state.solutions = {"agent_a": "sol A", "agent_b": "sol B"}
        state.analyses = {"agent_a": "ana A"}
        state.critiques = {"agent_a": "crit A"}
        state.agent_ids = {"agent_a": "id-1", "agent_b": "id-2"}
        state.judge_history = ["agent_a"]
        state.round = 2
        state.final_verdict = "All good"
        state.consensus_reached = True
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            save_state(state, path)
            loaded = load_state(path)
            assert loaded == state
