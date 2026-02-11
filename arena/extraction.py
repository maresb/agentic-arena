"""Content extraction from agent conversations and committed files.

Primary extraction path: fetch committed files from agent branches.
Verdict: JSON (committed as verdict.json or fenced block in conversation).
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

logger = logging.getLogger("arena")


# ---------------------------------------------------------------------------
# Vote verdict model (JSON-based)
# ---------------------------------------------------------------------------


class Divergence(BaseModel):
    """A specific remaining divergence between agent solutions."""

    topic: str = ""
    description: str = ""


class VoteVerdict(BaseModel):
    """Structured verdict parsed from an agent's verdict.json file.

    The ``divergences`` list replaces the old ``remaining_disagreements``
    count, forcing agents to enumerate specific issues rather than
    reporting a vague number.

    Bidirectional enforcement:
    - Empty divergences → score must be 10  (full convergence)
    - Non-empty divergences → score must be ≤ 9
    """

    convergence_score: int | None = None
    best_solutions: list[str] = Field(default_factory=list)
    divergences: list[Divergence] = Field(default_factory=list)
    rationale: str | None = None
    # Legacy field — accepted during parsing but not used for new verdicts.
    remaining_disagreements: int | str | None = Field(default=None, exclude=True)


def _normalize_alias(raw: str) -> str:
    """Normalize a vote target to the canonical alias form.

    Agents sometimes write ``"Agent A"`` instead of ``"agent_a"``.
    Convert to lowercase and replace spaces with underscores.
    """
    return raw.strip().lower().replace(" ", "_")


def _enforce_divergence_score(verdict: VoteVerdict) -> None:
    """Enforce bidirectional divergence/score constraint in place.

    - Empty divergences → score must be 10
    - Non-empty divergences → score must be ≤ 9
    """
    if verdict.convergence_score is None:
        return
    has_divergences = len(verdict.divergences) > 0
    if not has_divergences and verdict.convergence_score < 10:
        logger.warning(
            "No divergences listed but score=%d; overriding to 10",
            verdict.convergence_score,
        )
        verdict.convergence_score = 10
    elif has_divergences and verdict.convergence_score >= 10:
        logger.warning(
            "%d divergences listed but score=%d; capping at 9",
            len(verdict.divergences),
            verdict.convergence_score,
        )
        verdict.convergence_score = 9


def parse_vote_verdict_json(
    text: str, *, valid_aliases: frozenset[str] | None = None
) -> VoteVerdict:
    """Parse a vote verdict from JSON text.

    Primary path: ``json.loads(text)`` directly (for file content fetched
    from a branch).

    Fallback: extract JSON from a fenced ``json`` code block in
    conversation text, then parse.

    Aliases in ``best_solutions`` are normalized (lowered, spaces →
    underscores).  If *valid_aliases* is provided, entries that don't
    match any known alias after normalization are dropped with a warning.

    Returns a :class:`VoteVerdict` with whatever fields could be parsed.
    On complete failure, returns a default (empty) verdict.
    """

    def _validate(data: dict) -> VoteVerdict:
        verdict = VoteVerdict.model_validate(data)
        normalized = [_normalize_alias(a) for a in verdict.best_solutions]
        if valid_aliases is not None:
            kept = [a for a in normalized if a in valid_aliases]
            dropped = [a for a in normalized if a not in valid_aliases]
            if dropped:
                logger.warning("Dropped unknown vote targets: %s", dropped)
            normalized = kept
        verdict.best_solutions = normalized
        _enforce_divergence_score(verdict)
        return verdict

    # ── Primary: direct JSON parse ──
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _validate(data)
    except (json.JSONDecodeError, ValueError):
        pass

    # ── Fallback: extract from fenced code block ──
    # Matches ```json ... ``` or ``` ... ``` containing JSON
    pattern = r"```(?:json)?\s*\n(.*?)\n\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                logger.info("Parsed verdict from fenced JSON code block")
                return _validate(data)
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Failed to parse vote verdict from text")
    return VoteVerdict()


# ---------------------------------------------------------------------------
# Conversation helpers
# ---------------------------------------------------------------------------


def is_assistant_message(msg: dict) -> bool:
    """Check if a conversation message is from the assistant.

    Supports both the real Cloud Agents API format (``type: assistant_message``)
    and the legacy mock format (``role: assistant``).
    """
    return msg.get("type") == "assistant_message" or msg.get("role") == "assistant"


def _get_latest_assistant_message(conversation: list[dict]) -> str:
    """Find the last assistant message in a conversation.

    Supports both the real API format (``type``/``text``) and the legacy
    mock format (``role``/``content``) so existing tests keep working.
    """
    for msg in reversed(conversation):
        if not is_assistant_message(msg):
            continue
        # Real Cloud Agents API format
        if msg.get("type") == "assistant_message":
            return msg.get("text", "")
        # Legacy / mock format
        return msg.get("content", "")
    raise ValueError("No assistant message found in conversation")


def extract_latest_response(conversation: list[dict]) -> str:
    """Extract the most recent assistant message."""
    return _get_latest_assistant_message(conversation)


# ---------------------------------------------------------------------------
# Re-prompt templates
# ---------------------------------------------------------------------------

# Re-prompt for when an agent didn't commit the expected file
FILE_COMMIT_RETRY_PROMPT = """You did not commit the expected arena output file:
  {expected_path}

Please create and commit this file now. The arena commit must:
  - contain ONLY files under arenas/
  - use the commit message: [arena] {commit_desc}
  - be your LAST commit (after any code changes)
"""
