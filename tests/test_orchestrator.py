"""Tests for the orchestrator and report generation."""

import os
import tempfile
from unittest.mock import patch, MagicMock

from arena.orchestrator import _archive_round, generate_final_report, step_once
from arena.state import Phase, init_state, save_state


class TestGenerateFinalReport:
    def test_report_created(self) -> None:
        state = init_state(task="Test task", repo="owner/repo")
        state.round = 1
        state.consensus_reached = True
        state.final_verdict = "All agents agree."
        state.solutions = {
            "agent_a": "Solution A",
            "agent_b": "Solution B",
            "agent_c": "Solution C",
        }
        state.analyses = {
            "agent_a": "Analysis A",
            "agent_b": "Analysis B",
            "agent_c": "Analysis C",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_final_report(state, tmpdir)
            report_path = os.path.join(tmpdir, "report.md")
            assert os.path.exists(report_path)

            with open(report_path) as f:
                content = f.read()

            assert "# Arena Report" in content
            assert "Test task" in content
            assert "Consensus:** Yes" in content
            assert "Solution A" in content
            assert "Solution B" in content
            assert "Solution C" in content
            assert "All agents agree." in content

    def test_report_without_consensus(self) -> None:
        state = init_state(task="Hard task", repo="owner/repo")
        state.round = 3
        state.consensus_reached = False
        state.final_verdict = "Still disagreeing."
        state.solutions = {"agent_a": "Sol"}
        state.analyses = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_final_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "Consensus:** No" in content

    def test_report_includes_alias_mapping(self) -> None:
        state = init_state(task="test", repo="r")
        state.final_verdict = "verdict"
        state.solutions = {}
        state.analyses = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_final_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "alias_mapping" in content.lower() or "Alias mapping" in content

    def test_report_includes_verify_results(self) -> None:
        state = init_state(
            task="test",
            repo="r",
            verify_commands=["pixi run pytest", "pixi run mypy ."],
        )
        state.final_verdict = "All good"
        state.solutions = {"agent_a": "Sol"}
        state.analyses = {}
        state.verify_results = ["All tests passed", "No type errors"]

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_final_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "Verify Command Results" in content
            assert "pixi run pytest" in content
            assert "All tests passed" in content
            assert "pixi run mypy ." in content
            assert "No type errors" in content


class TestArchiveRound:
    def test_archives_solutions_and_analyses(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {"agent_a": "Sol A", "agent_b": "Sol B", "agent_c": "Sol C"}
        state.analyses = {"agent_a": "Ana A", "agent_b": "Ana B", "agent_c": "Ana C"}

        with tempfile.TemporaryDirectory() as tmpdir:
            _archive_round(state, tmpdir)
            files = os.listdir(tmpdir)
            solution_files = [f for f in files if "solution" in f]
            analysis_files = [f for f in files if "analysis" in f]
            assert len(solution_files) == 3
            assert len(analysis_files) == 3
            # Verify new naming format: {round}-{phase}-{model}-{type}-{uid}.md
            for f in solution_files:
                assert f.startswith("00-solve-")
                assert "-solution-" in f
                assert f.endswith(".md")

    def test_archives_critiques(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {}
        state.analyses = {}
        state.critiques = {"agent_a": "Crit A"}

        with tempfile.TemporaryDirectory() as tmpdir:
            _archive_round(state, tmpdir)
            files = os.listdir(tmpdir)
            critique_files = [f for f in files if "critique" in f]
            assert len(critique_files) == 1
            assert critique_files[0].startswith("00-evaluate-")

    def test_archives_verdict_on_done(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {}
        state.analyses = {}
        state.phase = Phase.DONE
        state.final_verdict = "All agents agree."
        state.judge_history = ["agent_b"]

        with tempfile.TemporaryDirectory() as tmpdir:
            _archive_round(state, tmpdir)
            files = os.listdir(tmpdir)
            verdict_files = [f for f in files if "verdict" in f]
            assert len(verdict_files) == 1
            assert verdict_files[0].startswith("00-verify-")

    def test_empty_state_produces_no_files(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {}
        state.analyses = {}
        state.critiques = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            _archive_round(state, tmpdir)
            files = [f for f in os.listdir(tmpdir) if f.endswith(".md")]
            assert files == []

    def test_archive_deduplication(self) -> None:
        """Archiving the same content twice should not create duplicate files."""
        state = init_state(task="test", repo="r")
        state.solutions = {"agent_a": "Sol A"}
        state.analyses = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            _archive_round(state, tmpdir)
            _archive_round(state, tmpdir)
            files = [f for f in os.listdir(tmpdir) if "solve" in f]
            assert len(files) == 1


class TestStepOnce:
    def test_raises_if_no_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            import pytest

            with pytest.raises(FileNotFoundError, match="No state file"):
                step_once(arena_dir=tmpdir)

    def test_raises_if_already_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task="test", repo="r")
            state.completed = True
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            import pytest

            with pytest.raises(RuntimeError, match="already completed"):
                step_once(arena_dir=tmpdir)

    def test_dispatches_solve_phase(self) -> None:
        """step_once should invoke the solve handler and save state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = init_state(task="test", repo="r")
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            mock_api = MagicMock()
            ids = iter(["id-1", "id-2", "id-3"])
            mock_api.launch.side_effect = lambda **kw: {"id": next(ids)}
            mock_api.status.return_value = {"status": "FINISHED"}

            conversation = [
                {
                    "role": "assistant",
                    "content": (
                        "<solution>\n## PLAN\nStep 1\n</solution>\n"
                        "<analysis>\n## RISKS\nNone\n</analysis>"
                    ),
                }
            ]
            mock_api.get_conversation.return_value = conversation

            with patch("arena.orchestrator._make_api", return_value=mock_api):
                result = step_once(arena_dir=tmpdir)

            assert result.phase == Phase.EVALUATE
            assert len(result.agent_ids) == 3
