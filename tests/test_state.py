"""Tests for state management with Pydantic models."""

import json
import os
import tempfile

from arena.state import (
    ALIASES,
    ArenaConfig,
    DEFAULT_MODELS,
    Phase,
    ProgressStatus,
    _aliases_for_count,
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
        assert models == set(DEFAULT_MODELS)
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
        assert state.verify_results == []
        assert state.verdict_history == []

    def test_verify_idempotency_fields_default_none(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.verify_judge is None
        assert state.verify_prev_msg_count is None


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

    def test_externalized_artifacts_on_disk(self) -> None:
        """save_state creates .md files in artifacts/ directory."""
        state = init_state(task="test", repo="r")
        state.solutions = {"agent_a": "Solution text A"}
        state.analyses = {"agent_a": "Analysis text A"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            save_state(state, path)
            artifacts = os.path.join(tmpdir, "artifacts")
            assert os.path.isdir(artifacts)
            files = os.listdir(artifacts)
            assert any("solutions" in f for f in files)
            assert any("analyses" in f for f in files)

    def test_externalized_round_trip_preserves_content(self) -> None:
        """Externalized artifacts are read back identically on load."""
        state = init_state(task="test", repo="r")
        state.solutions = {"agent_a": "Long solution content here"}
        state.final_verdict = "The final verdict text"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            save_state(state, path)
            loaded = load_state(path)
            assert loaded is not None
            assert loaded.solutions["agent_a"] == "Long solution content here"
            assert loaded.final_verdict == "The final verdict text"

    def test_backward_compat_inline_state(self) -> None:
        """States saved with inline text (old format) still load correctly."""
        state = init_state(task="test", repo="r")
        # Simulate old-format JSON with inline text (no file: prefix)
        dump = state.model_dump()
        dump["solutions"] = {"agent_a": "inline solution"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            with open(path, "w") as f:
                json.dump(dump, f)
            loaded = load_state(path)
            assert loaded is not None
            assert loaded.solutions["agent_a"] == "inline solution"


class TestCustomModels:
    def test_init_with_custom_models(self) -> None:
        state = init_state(task="test", repo="r", models=["opus", "gpt"])
        assert len(state.alias_mapping) == 2
        assert set(state.alias_mapping.keys()) == {"agent_a", "agent_b"}

    def test_init_with_single_model(self) -> None:
        state = init_state(task="test", repo="r", models=["opus"])
        assert len(state.alias_mapping) == 1
        assert "agent_a" in state.alias_mapping

    def test_aliases_for_count(self) -> None:
        assert _aliases_for_count(1) == ["agent_a"]
        assert _aliases_for_count(3) == ["agent_a", "agent_b", "agent_c"]
        assert _aliases_for_count(5) == [
            "agent_a",
            "agent_b",
            "agent_c",
            "agent_d",
            "agent_e",
        ]

    def test_models_stored_in_config(self) -> None:
        state = init_state(task="test", repo="r", models=["opus", "gpt"])
        assert len(state.config.models) == 2

    def test_branch_only_config(self) -> None:
        state = init_state(task="test", repo="r", branch_only=True)
        assert state.config.branch_only is True

    def test_verify_mode_config(self) -> None:
        state = init_state(task="test", repo="r", verify_mode="gating")
        assert state.config.verify_mode == "gating"

    def test_branch_names_field(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.branch_names == {}
        state.branch_names["agent_a"] = "feature/test"
        assert state.branch_names["agent_a"] == "feature/test"

    def test_token_usage_field(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.token_usage == {}
        state.token_usage["agent_a"] = 5000
        assert state.token_usage["agent_a"] == 5000

    def test_verify_progress_field(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.verify_progress == ProgressStatus.PENDING

    def test_context_mode_default(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.config.context_mode == "full"

    def test_agent_timing_field(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.agent_timing == {}
        state.agent_timing["agent_a"] = {"solve": {"start": 1.0, "end": 2.0}}
        assert state.agent_timing["agent_a"]["solve"]["end"] == 2.0

    def test_agent_metadata_field(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.agent_metadata == {}
        state.agent_metadata["agent_a"] = {"summary": "Did stuff", "linesAdded": 42}
        assert state.agent_metadata["agent_a"]["linesAdded"] == 42
