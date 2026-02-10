"""Tests for prompt templates."""

from arena.prompts import (
    evaluate_prompt,
    revise_prompt,
    solve_prompt,
)
from arena.state import DEFAULT_MODEL_NICKNAMES


class TestSolvePrompt:
    def test_contains_task(self) -> None:
        prompt = solve_prompt("Refactor the auth module", "agent_a", 1, 0)
        assert "Refactor the auth module" in prompt

    def test_contains_alias(self) -> None:
        prompt = solve_prompt("task", "agent_b", 1, 0)
        assert "agent_b" in prompt

    def test_contains_file_paths(self) -> None:
        prompt = solve_prompt("task", "agent_a", 3, 0)
        assert "arenas/0003/00-1-solve-agent_a-solution.md" in prompt
        assert "arenas/0003/00-1-solve-agent_a-analysis.md" in prompt

    def test_contains_section_headers(self) -> None:
        prompt = solve_prompt("task", "agent_a", 1, 0)
        assert "## PLAN" in prompt
        assert "## CHANGES" in prompt
        assert "## RISKS" in prompt
        assert "## OPEN QUESTIONS" in prompt

    def test_contains_commit_convention(self) -> None:
        prompt = solve_prompt("task", "agent_a", 1, 0)
        assert "[arena]" in prompt
        assert "LAST commit" in prompt


def _make_agent_files() -> list[tuple[str, str, str, str]]:
    """Build sample agent_files for evaluate prompt tests."""
    return [
        (
            "agent_a",
            "cursor/branch-a",
            "arenas/0001/00-1-solve-agent_a-solution.md",
            "arenas/0001/00-1-solve-agent_a-analysis.md",
        ),
        (
            "agent_b",
            "cursor/branch-b",
            "arenas/0001/00-1-solve-agent_b-solution.md",
            "arenas/0001/00-1-solve-agent_b-analysis.md",
        ),
    ]


class TestEvaluatePrompt:
    def test_contains_agent_labels(self) -> None:
        prompt = evaluate_prompt("agent_c", _make_agent_files(), 1, 0)
        assert "AGENT A" in prompt
        assert "AGENT B" in prompt

    def test_contains_branch_references(self) -> None:
        prompt = evaluate_prompt("agent_b", _make_agent_files(), 1, 0)
        assert "cursor/branch-a" in prompt
        assert "git show" in prompt
        assert "00-1-solve-agent_a-solution.md" in prompt

    def test_does_not_contain_solution_content(self) -> None:
        """Prompt should reference files, not paste content."""
        prompt = evaluate_prompt("agent_b", _make_agent_files(), 1, 0)
        # The prompt should NOT contain literal solution text
        assert "origin/" in prompt  # branch ref
        assert "git show" in prompt  # fetch instruction

    def test_contains_critique_instructions(self) -> None:
        prompt = evaluate_prompt("agent_a", _make_agent_files(), 1, 0)
        assert "Strengths" in prompt
        assert "Weaknesses" in prompt
        assert "Errors" in prompt

    def test_contains_verdict_schema(self) -> None:
        prompt = evaluate_prompt("agent_a", _make_agent_files(), 1, 0)
        assert "convergence_score" in prompt
        assert "best_solutions" in prompt
        assert "verdict" in prompt.lower()
        assert ".json" in prompt

    def test_contains_file_paths(self) -> None:
        prompt = evaluate_prompt("agent_b", _make_agent_files(), 3, 0)
        assert "arenas/0003/00-2-evaluate-agent_b-critique.md" in prompt
        assert "arenas/0003/00-2-evaluate-agent_b-verdict.json" in prompt

    def test_contains_commit_convention(self) -> None:
        prompt = evaluate_prompt("agent_a", _make_agent_files(), 1, 0)
        assert "[arena]" in prompt
        assert "LAST commit" in prompt

    def test_includes_own_alias_warning(self) -> None:
        prompt = evaluate_prompt("agent_a", _make_agent_files(), 1, 0)
        # Should tell agent to exclude self from voting
        assert "agent_a" in prompt


def _make_critique_files() -> list[tuple[str, str, str]]:
    """Build sample agent_critique_files for revise prompt tests."""
    return [
        ("agent_a", "cursor/branch-a", "arenas/0001/00-2-evaluate-agent_a-critique.md"),
        ("agent_b", "cursor/branch-b", "arenas/0001/00-2-evaluate-agent_b-critique.md"),
        ("agent_c", "cursor/branch-c", "arenas/0001/00-2-evaluate-agent_c-critique.md"),
    ]


class TestRevisePrompt:
    def test_contains_all_critique_references(self) -> None:
        prompt = revise_prompt("agent_a", _make_critique_files(), 1, 0)
        assert "AGENT A" in prompt
        assert "AGENT B" in prompt
        assert "AGENT C" in prompt
        assert "cursor/branch-a" in prompt
        assert "cursor/branch-b" in prompt
        assert "git show" in prompt

    def test_contains_file_paths(self) -> None:
        prompt = revise_prompt(
            "agent_a",
            [("agent_b", "cursor/b", "arenas/0003/01-2-evaluate-agent_b-critique.md")],
            3,
            1,
        )
        assert "arenas/0003/01-3-revise-agent_a-solution.md" in prompt
        assert "arenas/0003/01-3-revise-agent_a-analysis.md" in prompt

    def test_contains_section_instructions(self) -> None:
        prompt = revise_prompt("agent_a", _make_critique_files(), 1, 0)
        assert "## PLAN" in prompt
        assert "## DISAGREEMENTS" in prompt

    def test_contains_commit_convention(self) -> None:
        prompt = revise_prompt("agent_a", _make_critique_files(), 1, 0)
        assert "[arena]" in prompt
        assert "LAST commit" in prompt


class TestModelsMapping:
    def test_all_models_present(self) -> None:
        assert "opus" in DEFAULT_MODEL_NICKNAMES
        assert "gpt" in DEFAULT_MODEL_NICKNAMES
        assert "gemini" in DEFAULT_MODEL_NICKNAMES

    def test_model_values_are_strings(self) -> None:
        for model_name in DEFAULT_MODEL_NICKNAMES.values():
            assert isinstance(model_name, str)
            assert len(model_name) > 0
