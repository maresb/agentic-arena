"""Tests for content extraction from agent conversations."""

import json

import pytest

from arena.extraction import (
    FILE_COMMIT_RETRY_PROMPT,
    VoteVerdict,
    extract_latest_response,
    is_assistant_message,
    parse_vote_verdict_json,
)


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
# VoteVerdict model
# ---------------------------------------------------------------------------


class TestVoteVerdictModel:
    def test_defaults(self) -> None:
        v = VoteVerdict()
        assert v.convergence_score is None
        assert v.best_solutions == []
        assert v.rationale is None

    def test_full_verdict(self) -> None:
        v = VoteVerdict(
            convergence_score=9,
            best_solutions=["agent_a", "agent_b"],
            remaining_disagreements=0,
            rationale="Both solutions are equivalent",
        )
        assert v.convergence_score == 9
        assert v.best_solutions == ["agent_a", "agent_b"]
        assert v.remaining_disagreements == 0
        assert v.rationale == "Both solutions are equivalent"


# ---------------------------------------------------------------------------
# parse_vote_verdict_json
# ---------------------------------------------------------------------------


class TestParseVoteVerdictJson:
    def test_direct_json(self) -> None:
        data = {
            "convergence_score": 8,
            "best_solutions": ["agent_b"],
            "remaining_disagreements": 1,
            "rationale": "Agent B has the cleanest approach",
        }
        text = json.dumps(data)
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 8
        assert verdict.best_solutions == ["agent_b"]
        assert verdict.remaining_disagreements == 1
        assert verdict.rationale == "Agent B has the cleanest approach"

    def test_fenced_json_block(self) -> None:
        text = (
            "Here is my verdict:\n\n"
            "```json\n"
            '{"convergence_score": 7, "best_solutions": ["agent_c"], '
            '"remaining_disagreements": 2, "rationale": "Close but not yet"}\n'
            "```\n"
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 7
        assert verdict.best_solutions == ["agent_c"]

    def test_fenced_block_without_json_tag(self) -> None:
        text = (
            "My evaluation:\n\n"
            "```\n"
            '{"convergence_score": 9, "best_solutions": ["agent_a"]}\n'
            "```\n"
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 9
        assert verdict.best_solutions == ["agent_a"]

    def test_invalid_json_returns_empty_verdict(self) -> None:
        verdict = parse_vote_verdict_json("not json at all")
        assert verdict.convergence_score is None
        assert verdict.best_solutions == []

    def test_partial_fields(self) -> None:
        text = json.dumps({"convergence_score": 5})
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 5
        assert verdict.best_solutions == []

    def test_extra_fields_ignored(self) -> None:
        text = json.dumps(
            {
                "convergence_score": 9,
                "best_solutions": ["agent_a"],
                "extra_field": "ignored",
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 9

    def test_empty_string(self) -> None:
        verdict = parse_vote_verdict_json("")
        assert verdict.convergence_score is None

    def test_normalizes_alias_casing_and_spaces(self) -> None:
        """'Agent A' should become 'agent_a'."""
        text = json.dumps(
            {
                "convergence_score": 8,
                "best_solutions": ["Agent A", "Agent B"],
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.best_solutions == ["agent_a", "agent_b"]

    def test_valid_aliases_filter(self) -> None:
        text = json.dumps(
            {
                "convergence_score": 7,
                "best_solutions": ["agent_a", "unknown_agent"],
            }
        )
        valid = frozenset(["agent_a", "agent_b", "agent_c"])
        verdict = parse_vote_verdict_json(text, valid_aliases=valid)
        assert verdict.best_solutions == ["agent_a"]

    def test_valid_aliases_with_normalization(self) -> None:
        """'Agent C' → 'agent_c' which IS in valid set."""
        text = json.dumps(
            {
                "convergence_score": 9,
                "best_solutions": ["Agent C"],
            }
        )
        valid = frozenset(["agent_a", "agent_b", "agent_c"])
        verdict = parse_vote_verdict_json(text, valid_aliases=valid)
        assert verdict.best_solutions == ["agent_c"]


# ---------------------------------------------------------------------------
# is_assistant_message
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


# ---------------------------------------------------------------------------
# Real API format
# ---------------------------------------------------------------------------


class TestRealApiFormatExtraction:
    """Test extraction with the real Cloud Agents API format (type/text)."""

    def test_extract_latest_response_api_format(self) -> None:
        conversation = [
            {"type": "assistant_message", "text": "first"},
            {"type": "user_message", "text": "followup"},
            {"type": "assistant_message", "text": "second"},
        ]
        assert extract_latest_response(conversation) == "second"


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------


def test_file_commit_retry_prompt_is_defined() -> None:
    assert "{expected_path}" in FILE_COMMIT_RETRY_PROMPT
    assert "[arena]" in FILE_COMMIT_RETRY_PROMPT
