"""Content extraction from agent conversations.

Parses XML-delimited sections (solution, analysis, verdict) from agent
responses, with fallback heuristics when tags are missing.
"""

from __future__ import annotations

import logging
import re
from enum import StrEnum

from pydantic import BaseModel

logger = logging.getLogger("arena")


# ---------------------------------------------------------------------------
# Verdict model
# ---------------------------------------------------------------------------


class VerdictDecision(StrEnum):
    """Possible judge decisions."""

    CONSENSUS = "CONSENSUS"
    CONTINUE = "CONTINUE"


class Verdict(BaseModel):
    """Structured verdict parsed from the judge's response."""

    decision: VerdictDecision = VerdictDecision.CONTINUE
    convergence_score: int | None = None
    remaining_disagreements: int | str | None = None
    base_solution: str | None = None
    modifications: str | None = None


# ---------------------------------------------------------------------------
# XML extraction
# ---------------------------------------------------------------------------


def extract_xml_section(text: str, tag: str) -> str | None:
    """Extract content between <tag>...</tag>. Returns None if not found."""
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------------
# Conversation helpers
# ---------------------------------------------------------------------------


def _get_latest_assistant_message(conversation: list[dict]) -> str:
    """Find the last assistant message in a conversation.

    Supports both the real API format (``type``/``text``) and the legacy
    mock format (``role``/``content``) so existing tests keep working.
    """
    for msg in reversed(conversation):
        # Real Cloud Agents API format
        if msg.get("type") == "assistant_message":
            return msg.get("text", "")
        # Legacy / mock format
        if msg.get("role") == "assistant":
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


def extract_solution_and_analysis_from_latest(
    conversation: list[dict],
) -> tuple[str, str]:
    """Same as above but for revised responses (later in conversation)."""
    return extract_solution_and_analysis(conversation)


def extract_latest_response(conversation: list[dict]) -> str:
    """Extract the most recent assistant message."""
    return _get_latest_assistant_message(conversation)


# ---------------------------------------------------------------------------
# Verdict parsing
# ---------------------------------------------------------------------------


def parse_verdict(text: str) -> Verdict:
    """Parse the structured verdict from the judge's response.

    Returns a :class:`Verdict` with at least ``decision`` populated.
    Falls back to keyword scanning when no ``<verdict>`` tag is found.
    """
    verdict_xml = extract_xml_section(text, "verdict")
    if verdict_xml is None:
        # Fallback: scan for CONSENSUS or CONTINUE anywhere in text
        logger.warning("No <verdict> tag found; falling back to keyword scan")
        if re.search(r"\bCONSENSUS\b", text):
            return Verdict(decision=VerdictDecision.CONSENSUS)
        return Verdict()

    decision = VerdictDecision.CONTINUE
    convergence_score: int | None = None
    remaining_disagreements: int | str | None = None
    base_solution: str | None = None
    modifications: str | None = None

    for line in verdict_xml.splitlines():
        line = line.strip()
        if line.startswith("decision:"):
            value = line.split(":", 1)[1].strip().upper()
            if "CONSENSUS" in value:
                decision = VerdictDecision.CONSENSUS
        elif line.startswith("convergence_score:"):
            try:
                convergence_score = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("remaining_disagreements:"):
            try:
                remaining_disagreements = int(line.split(":", 1)[1].strip())
            except ValueError:
                remaining_disagreements = line.split(":", 1)[1].strip()
        elif line.startswith("base_solution:"):
            base_solution = line.split(":", 1)[1].strip()
        elif line.startswith("modifications:"):
            modifications = line.split(":", 1)[1].strip()

    return Verdict(
        decision=decision,
        convergence_score=convergence_score,
        remaining_disagreements=remaining_disagreements,
        base_solution=base_solution,
        modifications=modifications,
    )


# Re-prompt template for when extraction fails
RETRY_PROMPT = """Your previous response could not be parsed.
Please reformat using the required XML tags:

<solution>
[your solution content]
</solution>

<analysis>
[your analysis content]
</analysis>
"""
