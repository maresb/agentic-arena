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
# Verdict parsing
# ---------------------------------------------------------------------------


def _keyword_fallback(text: str) -> Verdict:
    """Fallback verdict extraction using structured patterns and keywords.

    Extraction priority (first match wins):
    1. ``decision: CONSENSUS`` / ``decision: CONTINUE`` pattern
    2. Last occurrence of a bare ``CONSENSUS`` or ``CONTINUE`` keyword

    If both keywords appear, the *last* occurrence wins (judges typically
    state the final decision at the end of their response).
    """
    # ── Priority 1: "decision: X" pattern (e.g. outside a verdict tag) ──
    decision_match = re.search(
        r"\bdecision\s*:\s*(CONSENSUS|CONTINUE)\b", text, re.IGNORECASE
    )
    if decision_match:
        value = decision_match.group(1).upper()
        logger.info("Keyword fallback: found 'decision: %s' pattern", value)
        if value == "CONSENSUS":
            return Verdict(decision=VerdictDecision.CONSENSUS)
        return Verdict(decision=VerdictDecision.CONTINUE)

    # ── Priority 2: bare keyword, prefer last occurrence ──
    last_consensus = -1
    last_continue = -1
    for m in re.finditer(r"\bCONSENSUS\b", text):
        last_consensus = m.start()
    for m in re.finditer(r"\bCONTINUE\b", text):
        last_continue = m.start()

    if last_consensus >= 0 or last_continue >= 0:
        if last_consensus > last_continue:
            logger.info("Keyword fallback: last keyword is CONSENSUS (pos %d)", last_consensus)
            return Verdict(decision=VerdictDecision.CONSENSUS)
        if last_continue > last_consensus:
            logger.info("Keyword fallback: last keyword is CONTINUE (pos %d)", last_continue)
            return Verdict(decision=VerdictDecision.CONTINUE)

    logger.warning("Keyword fallback: no CONSENSUS or CONTINUE keyword found")
    return Verdict()


def parse_verdict(text: str) -> Verdict:
    """Parse the structured verdict from the judge's response.

    Returns a :class:`Verdict` with at least ``decision`` populated.
    Falls back to keyword scanning when no ``<verdict>`` tag is found.
    """
    verdict_xml = extract_xml_section(text, "verdict")
    if verdict_xml is None:
        # Fallback: structured pattern search then bare keyword scan
        logger.warning("No <verdict> tag found; falling back to keyword scan")
        return _keyword_fallback(text)

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

# Re-prompt template for when verdict extraction falls back to keywords
VERDICT_RETRY_PROMPT = """Your verdict could not be reliably parsed.
Please re-emit ONLY the structured verdict block in this exact format:

<verdict>
decision: CONSENSUS or CONTINUE
convergence_score: [1-10]
remaining_disagreements: [count]
base_solution: [alias or "merged"]
modifications: [list of changes]
</verdict>
"""
