"""Prompt templates for each arena phase.

All prompts use XML-delimited output sections for robust parsing.
Presentation order is shuffled to prevent positional bias.
"""

import random


# ---------------------------------------------------------------------------
# Branch hint block (Phase 0 — agent branch visibility)
# ---------------------------------------------------------------------------
def _branch_hint_block(branch_names: dict[str, str] | None) -> str:
    """Return a prompt block listing agent branch names for cross-inspection.

    Returns an empty string when *branch_names* is ``None`` or empty,
    keeping prompts backward-compatible.
    """
    if not branch_names:
        return ""
    lines = [
        "",
        "--- Agent Branches ---",
        "Each agent's full work is committed to their branch. "
        "If a summary above seems incomplete, run "
        "`git fetch origin <branch>` and inspect their commits.",
        "",
    ]
    for alias, branch in sorted(branch_names.items()):
        label = alias.replace("_", " ").upper()
        lines.append(f"  {label}: {branch}")
    lines.append("")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Model identifier mapping (alias → Cursor API model name)
# ---------------------------------------------------------------------------
MODELS: dict[str, str] = {
    "opus": "claude-4.6-opus-high-thinking",
    "gpt": "gpt-5.2-codex-high",
    "gemini": "gemini-3-pro",  # temporarily unavailable
}

# ---------------------------------------------------------------------------
# Solve phase
# ---------------------------------------------------------------------------
SOLVE_TEMPLATE = """\
{task}

Write your response with these XML-delimited sections:

<solution>
## PLAN — Numbered key decisions with rationale.
## CHANGES — Unified diff or precise change descriptions.
</solution>

<analysis>
## RISKS — Known risks, edge cases, trade-offs.
## OPEN QUESTIONS — Uncertainties requiring verification.
</analysis>
"""


def solve_prompt(task: str) -> str:
    """Generate the initial solve prompt."""
    return SOLVE_TEMPLATE.format(task=task)


# ---------------------------------------------------------------------------
# Evaluate phase
# ---------------------------------------------------------------------------
EVALUATE_TEMPLATE = """\
Read these solutions from other agents:

{solutions_block}

Write a critique of each. DO NOT revise your own solution yet.

For each agent's solution:
- Strengths: what they do well.
- Weaknesses: what's wrong or suboptimal.
- Errors: anything factually incorrect.

Then state your position:
- What you're keeping from your original approach and why.
- What you'd adopt from others and why.
- What you still disagree on and why.
"""


def evaluate_prompt(
    others: list[tuple[str, str]],
    *,
    branch_names: dict[str, str] | None = None,
) -> str:
    """Generate the evaluate prompt with shuffled presentation order.

    Parameters
    ----------
    others:
        List of (alias, solution_text) tuples for the other two agents.
    branch_names:
        Optional mapping of alias → branch name for cross-inspection.
    """
    shuffled = list(others)
    random.shuffle(shuffled)
    blocks = []
    for alias, solution in shuffled:
        label = alias.replace("_", " ").upper()
        blocks.append(f"=== {label} ===\n{solution}")
    solutions_block = "\n\n".join(blocks)
    text = EVALUATE_TEMPLATE.format(solutions_block=solutions_block)
    return text + _branch_hint_block(branch_names)


# ---------------------------------------------------------------------------
# Revise phase
# ---------------------------------------------------------------------------
REVISE_TEMPLATE = """\
Here is how all three agents (including you) were critiqued:

{critiques_block}

Produce your REVISED solution, incorporating the strongest elements.
Use the same XML-delimited format:

<solution>
## PLAN and ## CHANGES as before.
</solution>

<analysis>
## RISKS, ## OPEN QUESTIONS as before.
## DISAGREEMENTS — Any remaining substantive disagreements
with the other approaches, or "None."
</analysis>
"""


def revise_prompt(
    all_critiques: list[tuple[str, str]],
    *,
    branch_names: dict[str, str] | None = None,
) -> str:
    """Generate the revise prompt with shuffled critique order.

    Parameters
    ----------
    all_critiques:
        List of (alias, critique_text) tuples for all three agents.
    branch_names:
        Optional mapping of alias → branch name for cross-inspection.
    """
    shuffled = list(all_critiques)
    random.shuffle(shuffled)
    blocks = []
    for alias, critique in shuffled:
        label = alias.replace("_", " ").upper()
        blocks.append(f"=== CRITIQUE BY {label} ===\n{critique}")
    critiques_block = "\n\n".join(blocks)
    text = REVISE_TEMPLATE.format(critiques_block=critiques_block)
    return text + _branch_hint_block(branch_names)


# ---------------------------------------------------------------------------
# Verify phase
# ---------------------------------------------------------------------------
VERIFY_TEMPLATE = """\
You are the consensus judge. You are one of the three contributors,
but you do not know which alias is yours. Judge each solution purely
on its technical merit, not on stylistic familiarity.

Read these revised solutions:

{solutions_block}

And these self-reported analyses (including any remaining disagreements):

{analyses_block}

Perform this analysis in order:

AGREEMENT POINTS — Specific points where all three converge.

DISAGREEMENT POINTS — Every remaining difference. For each:
state which approach is correct and why.

MOST SIGNIFICANT DIFFERENCE — Identify the single biggest remaining
difference. Is it trivial (style/naming) or substantive (logic/architecture)?

CONVERGENCE SCORE — 1-10. Score 8+ only if all remaining differences
are trivial (style, naming, formatting). Any substantive disagreement
on logic, architecture, or correctness caps the score at 7.

Wrap your structured verdict in XML:

<verdict>
decision: CONSENSUS or CONTINUE
convergence_score: [1-10]
remaining_disagreements: [count]
base_solution: [alias of best solution to use as base, or "merged"]
modifications: [list of specific changes to apply from other solutions]
</verdict>

If CONSENSUS (score >= 8): identify the best base solution by alias
and enumerate specific modifications to incorporate from the others.
Do NOT regenerate the full solution from scratch.

If CONTINUE (score < 8): describe the substantive disagreements
that need resolution in the next round.
"""


def verify_prompt(
    solutions: list[tuple[str, str]],
    analyses: list[tuple[str, str]],
    *,
    branch_names: dict[str, str] | None = None,
) -> str:
    """Generate the verify prompt with shuffled solution order.

    Parameters
    ----------
    solutions:
        List of (alias, solution_text) tuples.
    analyses:
        List of (alias, analysis_text) tuples.
    branch_names:
        Optional mapping of alias → branch name for cross-inspection.
    """
    shuffled_solutions = list(solutions)
    random.shuffle(shuffled_solutions)

    sol_blocks = []
    for alias, solution in shuffled_solutions:
        label = alias.replace("_", " ").upper()
        sol_blocks.append(f"=== {label} SOLUTION ===\n{solution}")
    solutions_block = "\n\n".join(sol_blocks)

    # Keep analysis order matching the shuffled solution order
    analyses_dict = dict(analyses)
    ana_blocks = []
    for alias, _ in shuffled_solutions:
        label = alias.replace("_", " ").upper()
        ana_text = analyses_dict.get(alias, "N/A")
        ana_blocks.append(f"=== {label} ANALYSIS ===\n{ana_text}")
    analyses_block = "\n\n".join(ana_blocks)

    text = VERIFY_TEMPLATE.format(
        solutions_block=solutions_block,
        analyses_block=analyses_block,
    )
    return text + _branch_hint_block(branch_names)
