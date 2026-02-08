"""Content extraction from agent conversations.

Parses XML-delimited sections (solution, analysis, verdict) from agent
responses, with fallback heuristics when tags are missing.
"""

import logging
import re

logger = logging.getLogger("arena")


def extract_xml_section(text: str, tag: str) -> str | None:
    """Extract content between <tag>...</tag>. Returns None if not found."""
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else None


def _get_latest_assistant_message(conversation: list[dict]) -> str:
    """Find the last assistant message in a conversation."""
    for msg in reversed(conversation):
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


def parse_verdict(text: str) -> dict:
    """Parse the structured verdict from the judge's response.

    Returns a dict with at least 'decision' (CONSENSUS or CONTINUE)
    and 'convergence_score' (int or None).
    """
    verdict_xml = extract_xml_section(text, "verdict")
    if verdict_xml is None:
        # Fallback: scan for CONSENSUS or CONTINUE anywhere in text
        logger.warning("No <verdict> tag found; falling back to keyword scan")
        if re.search(r"\bCONSENSUS\b", text):
            return {"decision": "CONSENSUS", "convergence_score": None}
        return {"decision": "CONTINUE", "convergence_score": None}

    result: dict[str, str | int | None] = {
        "decision": "CONTINUE",
        "convergence_score": None,
        "remaining_disagreements": None,
        "base_solution": None,
        "modifications": None,
    }
    for line in verdict_xml.splitlines():
        line = line.strip()
        if line.startswith("decision:"):
            value = line.split(":", 1)[1].strip().upper()
            if "CONSENSUS" in value:
                result["decision"] = "CONSENSUS"
        elif line.startswith("convergence_score:"):
            try:
                result["convergence_score"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("remaining_disagreements:"):
            try:
                result["remaining_disagreements"] = int(
                    line.split(":", 1)[1].strip()
                )
            except ValueError:
                result["remaining_disagreements"] = line.split(":", 1)[1].strip()
        elif line.startswith("base_solution:"):
            result["base_solution"] = line.split(":", 1)[1].strip()
        elif line.startswith("modifications:"):
            result["modifications"] = line.split(":", 1)[1].strip()
    return result


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
