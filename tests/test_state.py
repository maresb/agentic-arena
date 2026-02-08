"""Tests for state management."""

import json
import os
import tempfile

from arena.state import ALIASES, init_state, load_state, save_state


class TestInitState:
    def test_basic_fields(self) -> None:
        state = init_state(task="Review PR #42", repo="owner/repo")
        assert state["task"] == "Review PR #42"
        assert state["repo"] == "owner/repo"
        assert state["base_branch"] == "main"
        assert state["max_rounds"] == 3
        assert state["phase"] == "solve"
        assert state["round"] == 0
        assert state["completed"] is False
        assert state["consensus_reached"] is None

    def test_alias_mapping_is_shuffled(self) -> None:
        """The mapping is randomized, so all models appear but order varies."""
        state = init_state(task="test", repo="r")
        models = set(state["alias_mapping"].values())
        assert models == {"opus", "gpt", "gemini"}
        assert set(state["alias_mapping"].keys()) == set(ALIASES)

    def test_custom_options(self) -> None:
        state = init_state(
            task="test",
            repo="r",
            base_branch="develop",
            max_rounds=5,
            verify_commands=["pixi run pytest"],
        )
        assert state["base_branch"] == "develop"
        assert state["max_rounds"] == 5
        assert state["verify_commands"] == ["pixi run pytest"]

    def test_initial_progress(self) -> None:
        state = init_state(task="test", repo="r")
        for alias in ALIASES:
            assert state["phase_progress"][alias] == "pending"

    def test_empty_collections(self) -> None:
        state = init_state(task="test", repo="r")
        assert state["solutions"] == {}
        assert state["analyses"] == {}
        assert state["critiques"] == {}
        assert state["agent_ids"] == {}
        assert state["judge_history"] == []


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
            state = {"test": True}
            save_state(state, path)
            assert os.path.exists(path)
            with open(path) as f:
                assert json.load(f) == state

    def test_state_is_valid_json(self) -> None:
        state = init_state(task="json check", repo="r")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            save_state(state, path)
            with open(path) as f:
                raw = f.read()
            # Should be pretty-printed with indent
            parsed = json.loads(raw)
            assert parsed["task"] == "json check"
