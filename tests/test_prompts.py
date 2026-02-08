"""Tests for prompt templates."""

from arena.prompts import (
    MODELS,
    _branch_hint_block,
    evaluate_prompt,
    revise_prompt,
    solve_prompt,
    verify_prompt,
)


class TestSolvePrompt:
    def test_contains_task(self) -> None:
        prompt = solve_prompt("Refactor the auth module")
        assert "Refactor the auth module" in prompt

    def test_contains_xml_tags(self) -> None:
        prompt = solve_prompt("task")
        assert "<solution>" in prompt
        assert "</solution>" in prompt
        assert "<analysis>" in prompt
        assert "</analysis>" in prompt

    def test_contains_section_headers(self) -> None:
        prompt = solve_prompt("task")
        assert "## PLAN" in prompt
        assert "## CHANGES" in prompt
        assert "## RISKS" in prompt
        assert "## OPEN QUESTIONS" in prompt


class TestEvaluatePrompt:
    def test_contains_agent_labels(self) -> None:
        others = [("agent_a", "solution A"), ("agent_b", "solution B")]
        prompt = evaluate_prompt(others)
        assert "AGENT A" in prompt
        assert "AGENT B" in prompt

    def test_contains_solutions(self) -> None:
        others = [("agent_a", "my solution text"), ("agent_c", "other solution")]
        prompt = evaluate_prompt(others)
        assert "my solution text" in prompt
        assert "other solution" in prompt

    def test_contains_instructions(self) -> None:
        prompt = evaluate_prompt([("agent_a", "x"), ("agent_b", "y")])
        assert "DO NOT revise your own solution yet" in prompt
        assert "Strengths" in prompt
        assert "Weaknesses" in prompt
        assert "Errors" in prompt


class TestRevisePrompt:
    def test_contains_all_critiques(self) -> None:
        critiques = [
            ("agent_a", "critique from A"),
            ("agent_b", "critique from B"),
            ("agent_c", "critique from C"),
        ]
        prompt = revise_prompt(critiques)
        assert "critique from A" in prompt
        assert "critique from B" in prompt
        assert "critique from C" in prompt

    def test_contains_xml_format_reminder(self) -> None:
        prompt = revise_prompt([("agent_a", "c")])
        assert "<solution>" in prompt
        assert "<analysis>" in prompt
        assert "## DISAGREEMENTS" in prompt


class TestVerifyPrompt:
    def test_contains_solutions_and_analyses(self) -> None:
        solutions = [("agent_a", "sol A"), ("agent_b", "sol B"), ("agent_c", "sol C")]
        analyses = [("agent_a", "ana A"), ("agent_b", "ana B"), ("agent_c", "ana C")]
        prompt = verify_prompt(solutions, analyses)
        assert "sol A" in prompt
        assert "sol B" in prompt
        assert "sol C" in prompt
        assert "ana A" in prompt
        assert "ana B" in prompt
        assert "ana C" in prompt

    def test_contains_verdict_format(self) -> None:
        solutions = [("agent_a", "x")]
        analyses = [("agent_a", "y")]
        prompt = verify_prompt(solutions, analyses)
        assert "<verdict>" in prompt
        assert "CONSENSUS" in prompt
        assert "CONTINUE" in prompt
        assert "convergence_score" in prompt

    def test_judge_anti_bias_instruction(self) -> None:
        prompt = verify_prompt([("agent_a", "x")], [("agent_a", "y")])
        assert "you do not know which alias is yours" in prompt
        assert "technical merit" in prompt


class TestBranchHints:
    def test_empty_branch_names_returns_empty(self) -> None:
        assert _branch_hint_block(None) == ""
        assert _branch_hint_block({}) == ""

    def test_branch_names_included(self) -> None:
        result = _branch_hint_block({"agent_a": "br-a", "agent_b": "br-b"})
        assert "br-a" in result
        assert "br-b" in result
        assert "AGENT A" in result
        assert "git fetch" in result

    def test_evaluate_with_branch_names(self) -> None:
        branches = {"agent_a": "branch-a", "agent_b": "branch-b"}
        prompt = evaluate_prompt(
            [("agent_a", "sol"), ("agent_b", "sol2")],
            branch_names=branches,
        )
        assert "branch-a" in prompt
        assert "branch-b" in prompt

    def test_verify_with_branch_names(self) -> None:
        branches = {"agent_a": "branch-a"}
        prompt = verify_prompt(
            [("agent_a", "sol")],
            [("agent_a", "ana")],
            branch_names=branches,
        )
        assert "branch-a" in prompt


class TestModelsMapping:
    def test_all_models_present(self) -> None:
        assert "opus" in MODELS
        assert "gpt" in MODELS
        assert "gemini" in MODELS

    def test_model_values_are_strings(self) -> None:
        for model_name in MODELS.values():
            assert isinstance(model_name, str)
            assert len(model_name) > 0
