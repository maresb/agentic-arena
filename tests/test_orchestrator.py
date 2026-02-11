"""Tests for the orchestrator and report generation."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from arena.orchestrator import (
    _archive_round,
    _write_winning_solution,
    generate_final_report,
    latest_arena_dir,
    next_arena_dir,
    step_once,
    update_report,
)
from arena.state import Phase, init_state, save_state


class TestUpdateReport:
    """Tests for the rolling report generator."""

    def test_report_created(self) -> None:
        state = init_state(task="Test task", repo="owner/repo")

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            report_path = os.path.join(tmpdir, "report.md")
            assert os.path.exists(report_path)

            with open(report_path) as f:
                content = f.read()

            assert "# Arena Report" in content
            assert "Test task" in content

    def test_report_contains_agents_table(self) -> None:
        state = init_state(task="test", repo="r")

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "| Alias | Model |" in content
            assert "agent_a" in content

    def test_report_shows_consensus(self) -> None:
        state = init_state(task="test", repo="r")
        state.consensus_reached = True
        state.completed = True

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "Consensus:** Yes" in content

    def test_report_shows_no_consensus(self) -> None:
        state = init_state(task="Hard task", repo="r")
        state.consensus_reached = False
        state.completed = True

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "Consensus:** No" in content

    def test_report_includes_verdict_history_rounds(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {"agent_a": "Sol A", "agent_b": "Sol B", "agent_c": "Sol C"}
        state.analyses = {"agent_a": "Ana A", "agent_b": "Ana B", "agent_c": "Ana C"}
        state.verdict_history = [
            json.dumps(
                {
                    "votes": {"agent_a": ["agent_b"], "agent_b": ["agent_a"]},
                    "scores": {"agent_a": 8, "agent_b": 9},
                    "divergences": {},
                }
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "## Round 0" in content
            assert "Min score:** 8" in content

    def test_report_does_not_inline_solutions(self) -> None:
        """The new report should NOT inline full solution text."""
        state = init_state(task="test", repo="r")
        state.solutions = {"agent_a": "UNIQUE_SOLUTION_TEXT_MARKER"}
        state.analyses = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "UNIQUE_SOLUTION_TEXT_MARKER" not in content

    def test_report_includes_archive_links(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {"agent_a": "Sol A", "agent_b": "Sol B", "agent_c": "Sol C"}
        state.analyses = {"agent_a": "Ana A", "agent_b": "Ana B", "agent_c": "Ana C"}
        state.critiques = {"agent_a": "Crit A"}
        state.verdict_history = [
            json.dumps(
                {
                    "votes": {"agent_a": ["agent_b"]},
                    "scores": {"agent_a": 9},
                    "divergences": {},
                }
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "[solution](" in content
            assert "[analysis](" in content
            assert "[critique](" in content
            assert "[verdict](" in content

    def test_report_shows_winner(self) -> None:
        state = init_state(task="test", repo="r")
        state.verify_winner = "agent_a"
        state.consensus_reached = True

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "Winner" in content
            assert "agent_a" in content

    def test_report_includes_token_usage(self) -> None:
        state = init_state(task="test", repo="r")
        state.token_usage = {"agent_a": 5000}

        with tempfile.TemporaryDirectory() as tmpdir:
            update_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "Token Usage" in content
            assert "5,000" in content


class TestWriteWinningSolution:
    """Tests for the winning-solution.md generator."""

    def test_writes_winner(self) -> None:
        state = init_state(task="test", repo="owner/repo")
        state.verify_winner = "agent_a"
        state.verify_scores = {"agent_a": 10, "agent_b": 10}
        state.solutions = {"agent_a": "Winner solution text"}
        state.analyses = {"agent_a": "Winner analysis text"}

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_winning_solution(state, tmpdir)
            path = os.path.join(tmpdir, "winning-solution.md")
            assert os.path.exists(path)

            with open(path) as f:
                content = f.read()

            assert "# Winning Solution" in content
            assert "agent_a" in content
            assert "Winner solution text" in content
            assert "Winner analysis text" in content

    def test_skips_if_no_winner(self) -> None:
        state = init_state(task="test", repo="r")
        state.verify_winner = None

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_winning_solution(state, tmpdir)
            assert not os.path.exists(os.path.join(tmpdir, "winning-solution.md"))

    def test_includes_pr_link(self) -> None:
        state = init_state(task="test", repo="owner/repo")
        state.verify_winner = "agent_a"
        state.verify_scores = {"agent_a": 10}
        state.solutions = {"agent_a": "Sol"}
        state.branch_names = {"agent_a": "cursor/branch-123"}

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_winning_solution(state, tmpdir)
            with open(os.path.join(tmpdir, "winning-solution.md")) as f:
                content = f.read()
            assert "cursor/branch-123" in content
            assert "owner/repo" in content


class TestGenerateFinalReport:
    """Legacy wrapper should produce both report.md and winning-solution.md."""

    def test_creates_both_files(self) -> None:
        state = init_state(task="test", repo="r")
        state.verify_winner = "agent_a"
        state.verify_scores = {"agent_a": 10}
        state.consensus_reached = True
        state.solutions = {"agent_a": "Sol"}
        state.analyses = {"agent_a": "Ana"}

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_final_report(state, tmpdir)
            assert os.path.exists(os.path.join(tmpdir, "report.md"))
            assert os.path.exists(os.path.join(tmpdir, "winning-solution.md"))


class TestArchiveRound:
    def test_archives_solutions_and_analyses(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {
            "agent_a": "Sol A",
            "agent_b": "Sol B",
            "agent_c": "Sol C",
        }
        state.analyses = {
            "agent_a": "Ana A",
            "agent_b": "Ana B",
            "agent_c": "Ana C",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            _archive_round(state, tmpdir)
            files = os.listdir(tmpdir)
            solution_files = [f for f in files if "solution" in f]
            analysis_files = [f for f in files if "analysis" in f]
            assert len(solution_files) == 3
            assert len(analysis_files) == 3
            # Verify new naming: {round}-{phase_num}-{phase}-{model}-{type}-{uid}.md
            for f in solution_files:
                assert f.startswith("00-1-solve-")
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
            assert critique_files[0].startswith("00-2-evaluate-")

    def test_archives_verdicts(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {}
        state.analyses = {}
        state.verify_votes = {"agent_a": ["agent_b"]}
        state.verify_scores = {"agent_a": 9}

        with tempfile.TemporaryDirectory() as tmpdir:
            _archive_round(state, tmpdir)
            files = os.listdir(tmpdir)
            verdict_files = [f for f in files if "verdict" in f]
            assert len(verdict_files) == 1
            assert verdict_files[0].startswith("00-2-evaluate-")
            assert verdict_files[0].endswith(".json")

    def test_empty_state_produces_no_files(self) -> None:
        state = init_state(task="test", repo="r")
        state.solutions = {}
        state.analyses = {}
        state.critiques = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            _archive_round(state, tmpdir)
            files = [
                f
                for f in os.listdir(tmpdir)
                if f.endswith(".md") or f.endswith(".json")
            ]
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
            state = init_state(task="test", repo="owner/repo")
            save_state(state, os.path.join(tmpdir, "state.yaml"))

            mock_api = MagicMock()
            ids = iter(["id-1", "id-2", "id-3"])
            mock_api.launch.side_effect = lambda **kw: {"id": next(ids)}
            mock_api.status.return_value = {"status": "FINISHED"}

            base_conversation = [
                {
                    "role": "assistant",
                    "content": (
                        "<solution>\n## PLAN\nStep 1\n</solution>\n"
                        "<analysis>\n## RISKS\nNone\n</analysis>"
                    ),
                }
            ]

            # Simulate conversation growth on followups
            followup_counts: dict[str, int] = {}

            def mock_followup(agent_id: str, prompt: str) -> dict:
                followup_counts[agent_id] = followup_counts.get(agent_id, 0) + 1
                return {"id": agent_id}

            def mock_get_conversation(agent_id: str) -> list[dict]:
                n = followup_counts.get(agent_id, 0)
                result_conv = list(base_conversation)
                for _ in range(n):
                    result_conv.append({"role": "user", "content": "followup"})
                    result_conv.append(dict(base_conversation[-1]))
                return result_conv

            mock_api.followup.side_effect = mock_followup
            mock_api.get_conversation.side_effect = mock_get_conversation

            with patch("arena.orchestrator._make_api", return_value=mock_api):
                result = step_once(arena_dir=tmpdir)

            assert result.phase == Phase.EVALUATE
            assert len(result.agent_ids) == 3


class TestArenaDirectoryNumbering:
    def test_next_arena_dir_starts_at_0001(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "arenas")
            result = next_arena_dir(root)
            assert result == os.path.join(root, "0001")

    def test_next_arena_dir_increments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "arenas")
            os.makedirs(os.path.join(root, "0001"))
            os.makedirs(os.path.join(root, "0002"))
            result = next_arena_dir(root)
            assert result == os.path.join(root, "0003")

    def test_next_arena_dir_skips_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "arenas")
            os.makedirs(os.path.join(root, "0001"))
            os.makedirs(os.path.join(root, "0005"))
            result = next_arena_dir(root)
            assert result == os.path.join(root, "0006")

    def test_next_arena_dir_ignores_non_numeric(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "arenas")
            os.makedirs(os.path.join(root, "0001"))
            os.makedirs(os.path.join(root, "readme"))
            result = next_arena_dir(root)
            assert result == os.path.join(root, "0002")

    def test_next_arena_dir_creates_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "arenas")
            next_arena_dir(root)
            gitignore = os.path.join(root, ".gitignore")
            assert os.path.exists(gitignore)
            with open(gitignore) as f:
                assert f.read() == "*\n"

    def test_next_arena_dir_does_not_overwrite_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "arenas")
            os.makedirs(root)
            gitignore = os.path.join(root, ".gitignore")
            with open(gitignore, "w") as f:
                f.write("custom\n")
            next_arena_dir(root)
            with open(gitignore) as f:
                assert f.read() == "custom\n"

    def test_latest_arena_dir_returns_none_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "arenas")
            assert latest_arena_dir(root) is None

    def test_latest_arena_dir_returns_highest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "arenas")
            os.makedirs(os.path.join(root, "0001"))
            os.makedirs(os.path.join(root, "0003"))
            os.makedirs(os.path.join(root, "0002"))
            assert latest_arena_dir(root) == os.path.join(root, "0003")
