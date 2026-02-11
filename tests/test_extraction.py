"""Tests for content extraction from agent conversations."""

import json

import pytest

from arena.extraction import (
    FILE_COMMIT_RETRY_PROMPT,
    Divergence,
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
        assert v.divergences == []
        assert v.rationale is None

    def test_full_verdict_with_divergences(self) -> None:
        v = VoteVerdict(
            convergence_score=8,
            best_solutions=["agent_a", "agent_b"],
            divergences=[
                Divergence(topic="quantization", description="A uses Q4, C uses Q8")
            ],
            rationale="Close but quantization differs",
        )
        assert v.convergence_score == 8
        assert v.best_solutions == ["agent_a", "agent_b"]
        assert len(v.divergences) == 1
        assert v.divergences[0].topic == "quantization"
        assert v.rationale == "Close but quantization differs"

    def test_full_verdict_no_divergences(self) -> None:
        v = VoteVerdict(
            convergence_score=10,
            best_solutions=["agent_a"],
            divergences=[],
            rationale="Full convergence",
        )
        assert v.convergence_score == 10
        assert v.divergences == []

    def test_legacy_remaining_disagreements_accepted(self) -> None:
        """Old format with remaining_disagreements is still parseable."""
        v = VoteVerdict(
            convergence_score=10,
            remaining_disagreements=0,
        )
        assert v.convergence_score == 10


# ---------------------------------------------------------------------------
# parse_vote_verdict_json
# ---------------------------------------------------------------------------


class TestParseVoteVerdictJson:
    def test_direct_json_with_divergences(self) -> None:
        data = {
            "convergence_score": 8,
            "best_solutions": ["agent_b"],
            "divergences": [
                {
                    "topic": "caching",
                    "description": "Agent A uses Redis, B uses memcached",
                }
            ],
            "rationale": "Agent B has the cleanest approach",
        }
        text = json.dumps(data)
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 8
        assert verdict.best_solutions == ["agent_b"]
        assert len(verdict.divergences) == 1
        assert verdict.divergences[0].topic == "caching"
        assert verdict.rationale == "Agent B has the cleanest approach"

    def test_direct_json_no_divergences_overrides_score_to_10(self) -> None:
        data = {
            "convergence_score": 8,
            "best_solutions": ["agent_b"],
            "divergences": [],
            "rationale": "All agree",
        }
        text = json.dumps(data)
        verdict = parse_vote_verdict_json(text)
        # Empty divergences → score forced to 10
        assert verdict.convergence_score == 10

    def test_fenced_json_block(self) -> None:
        text = (
            "Here is my verdict:\n\n"
            "```json\n"
            '{"convergence_score": 7, "best_solutions": ["agent_c"], '
            '"divergences": [{"topic": "style", "description": "differs"}], '
            '"rationale": "Close but not yet"}\n'
            "```\n"
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 7
        assert verdict.best_solutions == ["agent_c"]

    def test_fenced_block_without_json_tag(self) -> None:
        text = (
            "My evaluation:\n\n"
            "```\n"
            '{"convergence_score": 10, "best_solutions": ["agent_a"], "divergences": []}\n'
            "```\n"
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 10
        assert verdict.best_solutions == ["agent_a"]

    def test_invalid_json_returns_empty_verdict(self) -> None:
        verdict = parse_vote_verdict_json("not json at all")
        assert verdict.convergence_score is None
        assert verdict.best_solutions == []

    def test_partial_fields_no_divergences_overrides(self) -> None:
        text = json.dumps({"convergence_score": 5})
        verdict = parse_vote_verdict_json(text)
        # No divergences → score forced to 10
        assert verdict.convergence_score == 10
        assert verdict.best_solutions == []

    def test_extra_fields_ignored(self) -> None:
        text = json.dumps(
            {
                "convergence_score": 10,
                "best_solutions": ["agent_a"],
                "divergences": [],
                "extra_field": "ignored",
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 10

    def test_empty_string(self) -> None:
        verdict = parse_vote_verdict_json("")
        assert verdict.convergence_score is None

    def test_normalizes_alias_casing_and_spaces(self) -> None:
        """'Agent A' should become 'agent_a'."""
        text = json.dumps(
            {
                "convergence_score": 10,
                "best_solutions": ["Agent A", "Agent B"],
                "divergences": [],
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.best_solutions == ["agent_a", "agent_b"]

    def test_valid_aliases_filter(self) -> None:
        text = json.dumps(
            {
                "convergence_score": 7,
                "best_solutions": ["agent_a", "unknown_agent"],
                "divergences": [{"topic": "x", "description": "y"}],
            }
        )
        valid = frozenset(["agent_a", "agent_b", "agent_c"])
        verdict = parse_vote_verdict_json(text, valid_aliases=valid)
        assert verdict.best_solutions == ["agent_a"]

    def test_valid_aliases_with_normalization(self) -> None:
        """'Agent C' → 'agent_c' which IS in valid set."""
        text = json.dumps(
            {
                "convergence_score": 10,
                "best_solutions": ["Agent C"],
                "divergences": [],
            }
        )
        valid = frozenset(["agent_a", "agent_b", "agent_c"])
        verdict = parse_vote_verdict_json(text, valid_aliases=valid)
        assert verdict.best_solutions == ["agent_c"]


class TestDivergenceScoreEnforcement:
    """Test the bidirectional divergence/score enforcement."""

    def test_no_divergences_low_score_overrides_to_10(self) -> None:
        text = json.dumps(
            {
                "convergence_score": 6,
                "best_solutions": ["agent_a"],
                "divergences": [],
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 10

    def test_divergences_present_score_10_capped_to_9(self) -> None:
        text = json.dumps(
            {
                "convergence_score": 10,
                "best_solutions": ["agent_a"],
                "divergences": [
                    {"topic": "naming", "description": "different var names"}
                ],
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 9

    def test_divergences_present_score_9_stays(self) -> None:
        text = json.dumps(
            {
                "convergence_score": 9,
                "best_solutions": ["agent_a"],
                "divergences": [
                    {"topic": "naming", "description": "different var names"}
                ],
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 9

    def test_no_divergences_score_10_stays(self) -> None:
        text = json.dumps(
            {
                "convergence_score": 10,
                "best_solutions": ["agent_a"],
                "divergences": [],
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score == 10

    def test_none_score_not_enforced(self) -> None:
        text = json.dumps(
            {
                "best_solutions": ["agent_a"],
                "divergences": [],
            }
        )
        verdict = parse_vote_verdict_json(text)
        assert verdict.convergence_score is None

    def test_legacy_remaining_disagreements_still_parseable(self) -> None:
        """Old format without divergences field — score gets overridden."""
        text = json.dumps(
            {
                "convergence_score": 7,
                "best_solutions": ["agent_a"],
                "remaining_disagreements": 2,
            }
        )
        verdict = parse_vote_verdict_json(text)
        # No divergences list → overridden to 10
        assert verdict.convergence_score == 10


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
