"""Content extraction from agent conversations and committed files.

Primary extraction path: fetch committed files from agent branches.
Fallback: parse XML-delimited sections from conversation text.
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


class VoteVerdict(BaseModel):
    """Structured verdict parsed from an agent's verdict.json file."""

    convergence_score: int | None = None
    best_solutions: list[str] = Field(default_factory=list)
    remaining_disagreements: int | str | None = None
    rationale: str | None = None


def parse_vote_verdict_json(text: str) -> VoteVerdict:
    """Parse a vote verdict from JSON text.

    Primary path: ``json.loads(text)`` directly (for file content fetched
    from a branch).

    Fallback: extract JSON from a fenced ``json`` code block in
    conversation text, then parse.

    Returns a :class:`VoteVerdict` with whatever fields could be parsed.
    On complete failure, returns a default (empty) verdict.
    """
    # ── Primary: direct JSON parse ──
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return VoteVerdict.model_validate(data)
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
                return VoteVerdict.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Failed to parse vote verdict from text")
    return VoteVerdict()


# ---------------------------------------------------------------------------
# XML extraction (conversation fallback for solution/analysis)
# ---------------------------------------------------------------------------


def extract_xml_section(text: str, tag: str) -> str | None:
    """Extract content between <tag>...</tag>. Returns None if not found."""
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else None


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


def extract_solution_and_analysis(
    conversation: list[dict],
) -> tuple[str, str]:
    """Extract solution and analysis from the latest assistant message."""
    text = _get_latest_assistant_message(conversation)
    solution = extract_xml_section(text, "solution")
    analysis = extract_xml_section(text, "analysis")

    if solution is None:
        logger.warning("No <solution> tag found; using full response as solution")
        solution = text
    if analysis is None:
        logger.warning("No <analysis> tag found; analysis will be empty")
        analysis = ""

    return solution, analysis


def extract_latest_response(conversation: list[dict]) -> str:
    """Extract the most recent assistant message."""
    return _get_latest_assistant_message(conversation)


# ---------------------------------------------------------------------------
# Re-prompt templates
# ---------------------------------------------------------------------------

# Re-prompt for when solution/analysis XML extraction fails (conversation fallback)
RETRY_PROMPT = """Your previous response could not be parsed.
Please reformat using the required XML tags:

<solution>
[your solution content]
</solution>

<analysis>
[your analysis content]
</analysis>
"""

# Re-prompt for when an agent didn't commit the expected file
FILE_COMMIT_RETRY_PROMPT = """You did not commit the expected arena output file:
  {expected_path}

Please create and commit this file now. The arena commit must:
  - contain ONLY files under arenas/
  - use the commit message: [arena] {commit_desc}
  - be your LAST commit (after any code changes)
"""
