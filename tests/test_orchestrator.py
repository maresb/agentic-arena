"""Tests for the orchestrator and report generation."""

import os
import tempfile

from arena.orchestrator import generate_final_report
from arena.state import init_state


class TestGenerateFinalReport:
    def test_report_created(self) -> None:
        state = init_state(task="Test task", repo="owner/repo")
        state["round"] = 1
        state["consensus_reached"] = True
        state["final_verdict"] = "All agents agree."
        state["solutions"] = {
            "agent_a": "Solution A",
            "agent_b": "Solution B",
            "agent_c": "Solution C",
        }
        state["analyses"] = {
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
        state["round"] = 3
        state["consensus_reached"] = False
        state["final_verdict"] = "Still disagreeing."
        state["solutions"] = {"agent_a": "Sol"}
        state["analyses"] = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_final_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "Consensus:** No" in content

    def test_report_includes_alias_mapping(self) -> None:
        state = init_state(task="test", repo="r")
        state["final_verdict"] = "verdict"
        state["solutions"] = {}
        state["analyses"] = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_final_report(state, tmpdir)
            with open(os.path.join(tmpdir, "report.md")) as f:
                content = f.read()
            assert "alias_mapping" in content.lower() or "Alias mapping" in content
