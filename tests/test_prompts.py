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


class TestEvaluatePrompt:
    def test_contains_agent_labels(self) -> None:
        solutions = [("agent_a", "solution A"), ("agent_b", "solution B")]
        analyses = [("agent_a", "analysis A"), ("agent_b", "analysis B")]
        prompt = evaluate_prompt("agent_c", solutions, analyses, 1, 0)
        assert "AGENT A" in prompt
        assert "AGENT B" in prompt

    def test_contains_solutions(self) -> None:
        solutions = [("agent_a", "my solution text"), ("agent_c", "other solution")]
        analyses = [("agent_a", ""), ("agent_c", "")]
        prompt = evaluate_prompt("agent_b", solutions, analyses, 1, 0)
        assert "my solution text" in prompt
        assert "other solution" in prompt

    def test_contains_critique_instructions(self) -> None:
        prompt = evaluate_prompt(
            "agent_a",
            [("agent_a", "x"), ("agent_b", "y")],
            [("agent_a", ""), ("agent_b", "")],
            1,
            0,
        )
        assert "Strengths" in prompt
        assert "Weaknesses" in prompt
        assert "Errors" in prompt

    def test_contains_verdict_schema(self) -> None:
        prompt = evaluate_prompt(
            "agent_a",
            [("agent_a", "x")],
            [("agent_a", "")],
            1,
            0,
        )
        assert "convergence_score" in prompt
        assert "best_solutions" in prompt
        assert "verdict" in prompt.lower()
        assert ".json" in prompt

    def test_contains_file_paths(self) -> None:
        prompt = evaluate_prompt(
            "agent_b",
            [("agent_a", "x")],
            [("agent_a", "")],
            3,
            0,
        )
        assert "arenas/0003/00-2-evaluate-agent_b-critique.md" in prompt
        assert "arenas/0003/00-2-evaluate-agent_b-verdict.json" in prompt

    def test_contains_commit_convention(self) -> None:
        prompt = evaluate_prompt(
            "agent_a",
            [("agent_a", "x")],
            [("agent_a", "")],
            1,
            0,
        )
        assert "[arena]" in prompt
        assert "LAST commit" in prompt

    def test_includes_own_alias_warning(self) -> None:
        prompt = evaluate_prompt(
            "agent_a",
            [("agent_a", "x"), ("agent_b", "y")],
            [("agent_a", ""), ("agent_b", "")],
            1,
            0,
        )
        # Should tell agent to exclude self from voting
        assert "agent_a" in prompt  # own alias mentioned


class TestRevisePrompt:
    def test_contains_all_critiques(self) -> None:
        critiques = [
            ("agent_a", "critique from A"),
            ("agent_b", "critique from B"),
            ("agent_c", "critique from C"),
        ]
        prompt = revise_prompt("agent_a", critiques, 1, 0)
        assert "critique from A" in prompt
        assert "critique from B" in prompt
        assert "critique from C" in prompt

    def test_contains_file_paths(self) -> None:
        prompt = revise_prompt("agent_a", [("agent_b", "c")], 3, 1)
        assert "arenas/0003/01-3-revise-agent_a-solution.md" in prompt
        assert "arenas/0003/01-3-revise-agent_a-analysis.md" in prompt

    def test_contains_section_instructions(self) -> None:
        prompt = revise_prompt("agent_a", [("agent_b", "c")], 1, 0)
        assert "## PLAN" in prompt
        assert "## DISAGREEMENTS" in prompt

    def test_contains_commit_convention(self) -> None:
        prompt = revise_prompt("agent_a", [("agent_b", "c")], 1, 0)
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
