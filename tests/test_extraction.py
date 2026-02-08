"""Tests for content extraction from agent conversations."""

import pytest

from arena.extraction import (
    RETRY_PROMPT,
    Verdict,
    VerdictDecision,
    extract_latest_response,
    extract_solution_and_analysis,
    extract_xml_section,
    is_assistant_message,
    parse_verdict,
)


# ---------------------------------------------------------------------------
# extract_xml_section
# ---------------------------------------------------------------------------


class TestExtractXmlSection:
    def test_basic_extraction(self) -> None:
        text = "preamble\n<solution>\nmy solution\n</solution>\npostamble"
        assert extract_xml_section(text, "solution") == "my solution"

    def test_multiline_content(self) -> None:
        text = "<analysis>\nline 1\nline 2\nline 3\n</analysis>"
        result = extract_xml_section(text, "analysis")
        assert result == "line 1\nline 2\nline 3"

    def test_missing_tag_returns_none(self) -> None:
        assert extract_xml_section("no tags here", "solution") is None

    def test_nested_content(self) -> None:
        text = "<verdict>\ndecision: CONSENSUS\nconvergence_score: 9\n</verdict>"
        result = extract_xml_section(text, "verdict")
        assert result is not None
        assert "decision: CONSENSUS" in result
        assert "convergence_score: 9" in result

    def test_whitespace_stripping(self) -> None:
        text = "<solution>  \n  content  \n  </solution>"
        assert extract_xml_section(text, "solution") == "content"

    def test_empty_content(self) -> None:
        text = "<solution></solution>"
        assert extract_xml_section(text, "solution") == ""


# ---------------------------------------------------------------------------
# extract_solution_and_analysis
# ---------------------------------------------------------------------------


class TestExtractSolutionAndAnalysis:
    def test_both_present(self) -> None:
        conversation = [
            {"role": "user", "content": "do something"},
            {
                "role": "assistant",
                "content": (
                    "Here is my work:\n"
                    "<solution>\n## PLAN\nStep 1\n## CHANGES\nDiff here\n</solution>\n"
                    "<analysis>\n## RISKS\nNone\n## OPEN QUESTIONS\nNone\n</analysis>"
                ),
            },
        ]
        solution, analysis = extract_solution_and_analysis(conversation)
        assert "## PLAN" in solution
        assert "Step 1" in solution
        assert "## RISKS" in analysis

    def test_missing_solution_uses_full_response(self) -> None:
        conversation = [
            {"role": "assistant", "content": "Just a plain response"},
        ]
        solution, analysis = extract_solution_and_analysis(conversation)
        assert solution == "Just a plain response"
        assert analysis == ""

    def test_missing_analysis_returns_empty(self) -> None:
        conversation = [
            {
                "role": "assistant",
                "content": "<solution>my solution</solution>",
            },
        ]
        solution, analysis = extract_solution_and_analysis(conversation)
        assert solution == "my solution"
        assert analysis == ""

    def test_no_assistant_message_raises(self) -> None:
        conversation = [{"role": "user", "content": "hello"}]
        with pytest.raises(ValueError, match="No assistant message"):
            extract_solution_and_analysis(conversation)


# ---------------------------------------------------------------------------
# extract_latest_response
# ---------------------------------------------------------------------------


class TestExtractLatestResponse:
    def test_returns_last_assistant(self) -> None:
        conversation = [
            {"role": "assistant", "content": "first"},
            {"role": "user", "content": "followup"},
            {"role": "assistant", "content": "second"},
        ]
        assert extract_latest_response(conversation) == "second"

    def test_empty_conversation_raises(self) -> None:
        with pytest.raises(ValueError):
            extract_latest_response([])


# ---------------------------------------------------------------------------
# Verdict model
# ---------------------------------------------------------------------------


class TestVerdictModel:
    def test_default_is_continue(self) -> None:
        v = Verdict()
        assert v.decision == VerdictDecision.CONTINUE
        assert v.convergence_score is None

    def test_consensus_verdict(self) -> None:
        v = Verdict(decision=VerdictDecision.CONSENSUS, convergence_score=9)
        assert v.decision == VerdictDecision.CONSENSUS
        assert v.convergence_score == 9


# ---------------------------------------------------------------------------
# parse_verdict
# ---------------------------------------------------------------------------


class TestParseVerdict:
    def test_consensus_verdict(self) -> None:
        text = (
            "Analysis here...\n"
            "<verdict>\n"
            "decision: CONSENSUS\n"
            "convergence_score: 9\n"
            "remaining_disagreements: 0\n"
            "base_solution: agent_a\n"
            "modifications: minor naming changes\n"
            "</verdict>"
        )
        verdict = parse_verdict(text)
        assert verdict.decision == VerdictDecision.CONSENSUS
        assert verdict.convergence_score == 9
        assert verdict.remaining_disagreements == 0
        assert verdict.base_solution == "agent_a"

    def test_continue_verdict(self) -> None:
        text = (
            "<verdict>\n"
            "decision: CONTINUE\n"
            "convergence_score: 5\n"
            "remaining_disagreements: 3\n"
            "base_solution: merged\n"
            "modifications: TBD\n"
            "</verdict>"
        )
        verdict = parse_verdict(text)
        assert verdict.decision == VerdictDecision.CONTINUE
        assert verdict.convergence_score == 5
        assert verdict.remaining_disagreements == 3

    def test_fallback_keyword_consensus(self) -> None:
        text = "After review, I declare CONSENSUS among all agents."
        verdict = parse_verdict(text)
        assert verdict.decision == VerdictDecision.CONSENSUS
        assert verdict.convergence_score is None

    def test_fallback_keyword_continue(self) -> None:
        text = "There are still disagreements to resolve."
        verdict = parse_verdict(text)
        assert verdict.decision == VerdictDecision.CONTINUE
        assert verdict.convergence_score is None

    def test_malformed_score_ignored(self) -> None:
        text = (
            "<verdict>\n"
            "decision: CONSENSUS\n"
            "convergence_score: high\n"
            "</verdict>"
        )
        verdict = parse_verdict(text)
        assert verdict.decision == VerdictDecision.CONSENSUS
        assert verdict.convergence_score is None

    def test_returns_verdict_instance(self) -> None:
        text = "<verdict>\ndecision: CONTINUE\n</verdict>"
        verdict = parse_verdict(text)
        assert isinstance(verdict, Verdict)


# ---------------------------------------------------------------------------
# RETRY_PROMPT exists and is non-empty
# ---------------------------------------------------------------------------


class TestIsAssistantMessage:
    def test_legacy_format(self) -> None:
        assert is_assistant_message({"role": "assistant", "content": "hi"}) is True

    def test_api_format(self) -> None:
        assert is_assistant_message({"type": "assistant_message", "text": "hi"}) is True

    def test_user_message_rejected(self) -> None:
        assert is_assistant_message({"role": "user", "content": "hi"}) is False

    def test_empty_dict(self) -> None:
        assert is_assistant_message({}) is False


class TestRealApiFormatExtraction:
    """Test extraction with the real Cloud Agents API format (type/text)."""

    def test_extract_solution_from_api_format(self) -> None:
        conversation = [
            {"type": "user_message", "text": "do something"},
            {
                "type": "assistant_message",
                "text": (
                    "<solution>\n## PLAN\nStep 1\n</solution>\n"
                    "<analysis>\n## RISKS\nNone\n</analysis>"
                ),
            },
        ]
        solution, analysis = extract_solution_and_analysis(conversation)
        assert "## PLAN" in solution
        assert "## RISKS" in analysis

    def test_extract_latest_response_api_format(self) -> None:
        conversation = [
            {"type": "assistant_message", "text": "first"},
            {"type": "user_message", "text": "followup"},
            {"type": "assistant_message", "text": "second"},
        ]
        assert extract_latest_response(conversation) == "second"


def test_retry_prompt_is_defined() -> None:
    assert "<solution>" in RETRY_PROMPT
    assert "<analysis>" in RETRY_PROMPT
