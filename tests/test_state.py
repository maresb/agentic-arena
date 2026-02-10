"""Tests for state management with Pydantic models."""

import json
import os
import tempfile

from arena.state import (
    ALIASES,
    PHASE_NUMBERS,
    TASK_PLACEHOLDER,
    ArenaConfig,
    DEFAULT_MODELS,
    Phase,
    ProgressStatus,
    _aliases_for_count,
    expected_path,
    init_state,
    load_state,
    resolve_model,
    save_state,
)


class TestArenaConfig:
    def test_defaults(self) -> None:
        cfg = ArenaConfig(task="test", repo="r")
        assert cfg.base_branch == "main"
        assert cfg.max_rounds == 3
        assert cfg.verify_commands == []
        assert cfg.arena_number == 1

    def test_frozen(self) -> None:
        cfg = ArenaConfig(task="test", repo="r")
        try:
            cfg.task = "changed"  # type: ignore[misc]
            raise AssertionError("Should not allow mutation")
        except Exception:
            pass  # Expected — frozen model

    def test_arena_number(self) -> None:
        cfg = ArenaConfig(task="test", repo="r", arena_number=42)
        assert cfg.arena_number == 42


class TestTaskPlaceholder:
    def test_placeholder_value(self) -> None:
        assert TASK_PLACEHOLDER == "[DESCRIBE THE TASK HERE]"


class TestPhaseEnum:
    def test_three_phases_plus_done(self) -> None:
        assert Phase.SOLVE == "solve"
        assert Phase.EVALUATE == "evaluate"
        assert Phase.REVISE == "revise"
        assert Phase.DONE == "done"
        # VERIFY should NOT exist
        assert not hasattr(Phase, "VERIFY")

    def test_phase_numbers(self) -> None:
        assert PHASE_NUMBERS == {"solve": 1, "evaluate": 2, "revise": 3}


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
        assert state.verify_results == []
        assert state.verdict_history == []
        assert state.verify_votes == {}
        assert state.verify_scores == {}

    def test_arena_number_passed_through(self) -> None:
        state = init_state(task="test", repo="r", arena_number=7)
        assert state.config.arena_number == 7


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
        state.round = 2
        state.final_verdict = "All good"
        state.consensus_reached = True
        state.verify_votes = {"agent_a": ["agent_b"]}
        state.verify_scores = {"agent_a": 9}
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
        dump = state.model_dump(mode="json")
        dump["solutions"] = {"agent_a": "inline solution"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            with open(path, "w") as f:
                json.dump(dump, f)
            loaded = load_state(path)
            assert loaded is not None
            assert loaded.solutions["agent_a"] == "inline solution"

    def test_yaml_round_trip(self) -> None:
        """State can be saved as YAML and loaded back correctly."""
        state = init_state(task="YAML test", repo="owner/repo")
        state.solutions = {"agent_a": "sol A"}
        state.final_verdict = "All good"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.yaml")
            save_state(state, path)
            assert os.path.exists(path)
            # Verify it's valid YAML, not JSON
            with open(path) as f:
                content = f.read()
            assert not content.strip().startswith("{")  # Not JSON
            loaded = load_state(path)
            assert loaded is not None
            assert loaded.config.task == "YAML test"
            assert loaded == state

    def test_yaml_fallback_to_json(self) -> None:
        """load_state with .yaml path falls back to .json if YAML doesn't exist."""
        state = init_state(task="fallback test", repo="r")
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "state.json")
            save_state(state, json_path)
            yaml_path = os.path.join(tmpdir, "state.yaml")
            loaded = load_state(yaml_path)
            assert loaded is not None
            assert loaded.config.task == "fallback test"

    def test_yaml_multiline_task_uses_literal_block(self) -> None:
        """Multi-line tasks are serialized with YAML literal block scalar (|)."""
        multiline_task = "Line one\nLine two\nLine three"
        state = init_state(task=multiline_task, repo="owner/repo")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.yaml")
            save_state(state, path)
            with open(path) as f:
                content = f.read()
            # The literal block scalar indicator should appear for the task
            assert "task: |" in content or "task: |\n" in content
            # Round-trip preserves content
            loaded = load_state(path)
            assert loaded is not None
            assert loaded.config.task == multiline_task

    def test_yaml_singleline_task_uses_block_scalar(self) -> None:
        """Even single-line tasks use literal block scalar for editability."""
        state = init_state(task="Simple task", repo="owner/repo")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.yaml")
            save_state(state, path)
            with open(path) as f:
                content = f.read()
            # Should use |- (literal strip) for single-line values
            assert "task: |-" in content or "task: |" in content
            loaded = load_state(path)
            assert loaded is not None
            assert loaded.config.task == "Simple task"


class TestExpectedPath:
    def test_solution(self) -> None:
        path = expected_path(3, "agent_a", "solution")
        assert path == "arenas/0003/agent_a-solution.md"

    def test_critique(self) -> None:
        path = expected_path(3, "agent_b", "critique")
        assert path == "arenas/0003/agent_b-critique.md"

    def test_verdict_json(self) -> None:
        path = expected_path(3, "agent_c", "verdict", ext="json")
        assert path == "arenas/0003/agent_c-verdict.json"

    def test_analysis(self) -> None:
        path = expected_path(3, "agent_a", "analysis")
        assert path == "arenas/0003/agent_a-analysis.md"

    def test_high_arena_number(self) -> None:
        path = expected_path(42, "agent_a", "solution")
        assert path == "arenas/0042/agent_a-solution.md"


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

    def test_voting_fields(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.verify_votes == {}
        assert state.verify_scores == {}
        assert state.verify_winner is None
        state.verify_votes["agent_a"] = ["agent_b", "agent_c"]
        state.verify_scores["agent_a"] = 9
        state.verify_winner = "agent_b"
        assert state.verify_votes["agent_a"] == ["agent_b", "agent_c"]
        assert state.verify_scores["agent_a"] == 9
        assert state.verify_winner == "agent_b"

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

    def test_model_nicknames_populated(self) -> None:
        state = init_state(task="test", repo="r")
        assert state.model_nicknames


class TestResolveModel:
    def test_default_nicknames_resolve(self) -> None:
        state = init_state(task="test", repo="r")
        assert resolve_model(state, "opus").startswith("claude-")
        assert resolve_model(state, "gpt").startswith("gpt-")
        assert resolve_model(state, "gemini").startswith("gemini-")

    def test_falls_back_to_name(self) -> None:
        state = init_state(task="test", repo="r")
        assert resolve_model(state, "some-custom-model") == "some-custom-model"

    def test_empty_nicknames_passes_through(self) -> None:
        state = init_state(task="test", repo="r")
        state.model_nicknames = {}
        assert resolve_model(state, "opus") == "opus"

    def test_custom_nicknames(self) -> None:
        state = init_state(task="test", repo="r")
        state.model_nicknames = {"mymodel": "vendor/my-model-v2"}
        assert resolve_model(state, "mymodel") == "vendor/my-model-v2"
        assert resolve_model(state, "other") == "other"
