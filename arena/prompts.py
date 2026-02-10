"""Prompt templates for each arena phase.

All prompts tell the agent its alias and exact file paths to commit.
Presentation order of other agents' content is shuffled to prevent
positional bias.
"""

import random

from arena.state import expected_path

# ---------------------------------------------------------------------------
# Commit convention block (included in every prompt)
# ---------------------------------------------------------------------------

_COMMIT_BLOCK = """\

IMPORTANT: Commit arena output files in a SEPARATE commit from any
code changes. The arena commit must:
  - contain ONLY the files listed above (nothing else)
  - use the commit message: [arena] {commit_desc}
  - be your LAST commit (after any code changes)"""


# ---------------------------------------------------------------------------
# Solve phase (phase 1)
# ---------------------------------------------------------------------------

SOLVE_TEMPLATE = """\
You are {alias}. {task}

After completing your work, commit your structured response as two files:
  {solution_path}
  {analysis_path}

{solution_path} should contain:
  ## PLAN — Numbered key decisions with rationale.
  ## CHANGES — Unified diff or precise change descriptions.

{analysis_path} should contain:
  ## RISKS — Known risks, edge cases, trade-offs.
  ## OPEN QUESTIONS — Uncertainties requiring verification.
{commit_block}"""


def solve_prompt(
    task: str,
    alias: str,
    arena_number: int,
    round_num: int,
) -> str:
    """Generate the initial solve prompt."""
    solution_path = expected_path(arena_number, round_num, "solve", alias, "solution")
    analysis_path = expected_path(arena_number, round_num, "solve", alias, "analysis")
    commit_desc = f"round {round_num:02d} solve {alias}"
    return SOLVE_TEMPLATE.format(
        alias=alias,
        task=task,
        solution_path=solution_path,
        analysis_path=analysis_path,
        commit_block=_COMMIT_BLOCK.format(commit_desc=commit_desc),
    )


# ---------------------------------------------------------------------------
# Evaluate phase (phase 2 — critique + vote)
# ---------------------------------------------------------------------------

EVALUATE_TEMPLATE = """\
You are {alias}. Read these solutions from all agents:

{solutions_block}

And these self-reported analyses:

{analyses_block}

Your task has two parts:

PART 1 — CRITIQUE (commit to {critique_path})

For each agent's solution:
- Strengths: what they do well.
- Weaknesses: what's wrong or suboptimal.
- Errors: anything factually incorrect.

Then state your position:
- What you're keeping from your original approach and why.
- What you'd adopt from others and why.
- What you still disagree on and why.

PART 2 — VERDICT (commit to {verdict_path})

{verdict_path} must be valid JSON with this exact schema:
{{
  "convergence_score": <1-10>,
  "best_solutions": [<aliases excluding your own ({alias}), at least one required>],
  "remaining_disagreements": <count>,
  "rationale": "<why these solutions are best / what still differs>"
}}

Score 8+ only if all remaining differences are trivial (style, naming,
formatting). Any substantive disagreement on logic, architecture, or
correctness caps the score at 7.

Vote for the best solution(s) OTHER than your own.

Commit both files:
  {critique_path}
  {verdict_path}
{commit_block}"""


def evaluate_prompt(
    alias: str,
    solutions: list[tuple[str, str]],
    analyses: list[tuple[str, str]],
    arena_number: int,
    round_num: int,
) -> str:
    """Generate the evaluate prompt with shuffled presentation order.

    Parameters
    ----------
    alias:
        The alias of the agent receiving this prompt.
    solutions:
        List of (alias, solution_text) tuples for ALL agents.
    analyses:
        List of (alias, analysis_text) tuples for ALL agents.
    """
    shuffled_solutions = list(solutions)
    random.shuffle(shuffled_solutions)

    sol_blocks = []
    for sol_alias, solution in shuffled_solutions:
        label = sol_alias.replace("_", " ").upper()
        sol_blocks.append(f"=== {label} SOLUTION ===\n{solution}")
    solutions_block = "\n\n".join(sol_blocks)

    # Keep analysis order matching the shuffled solution order
    analyses_dict = dict(analyses)
    ana_blocks = []
    for sol_alias, _ in shuffled_solutions:
        label = sol_alias.replace("_", " ").upper()
        ana_text = analyses_dict.get(sol_alias, "N/A")
        ana_blocks.append(f"=== {label} ANALYSIS ===\n{ana_text}")
    analyses_block = "\n\n".join(ana_blocks)

    critique_path = expected_path(
        arena_number, round_num, "evaluate", alias, "critique"
    )
    verdict_path = expected_path(
        arena_number, round_num, "evaluate", alias, "verdict", ext="json"
    )
    commit_desc = f"round {round_num:02d} evaluate {alias}"

    return EVALUATE_TEMPLATE.format(
        alias=alias,
        solutions_block=solutions_block,
        analyses_block=analyses_block,
        critique_path=critique_path,
        verdict_path=verdict_path,
        commit_block=_COMMIT_BLOCK.format(commit_desc=commit_desc),
    )


# ---------------------------------------------------------------------------
# Revise phase (phase 3)
# ---------------------------------------------------------------------------

REVISE_TEMPLATE = """\
You are {alias}. Here is how all agents were critiqued:

{critiques_block}

Produce your REVISED solution, incorporating the strongest elements.

Commit your revised response as two files:
  {solution_path}
  {analysis_path}

{solution_path} should contain:
  ## PLAN and ## CHANGES as before.

{analysis_path} should contain:
  ## RISKS, ## OPEN QUESTIONS as before.
  ## DISAGREEMENTS — Any remaining substantive disagreements
  with the other approaches, or "None."
{commit_block}"""


def revise_prompt(
    alias: str,
    all_critiques: list[tuple[str, str]],
    arena_number: int,
    round_num: int,
) -> str:
    """Generate the revise prompt with shuffled critique order.

    Parameters
    ----------
    alias:
        The alias of the agent receiving this prompt.
    all_critiques:
        List of (alias, critique_text) tuples for all agents.
    """
    shuffled = list(all_critiques)
    random.shuffle(shuffled)
    blocks = []
    for crit_alias, critique in shuffled:
        label = crit_alias.replace("_", " ").upper()
        blocks.append(f"=== CRITIQUE BY {label} ===\n{critique}")
    critiques_block = "\n\n".join(blocks)

    solution_path = expected_path(arena_number, round_num, "revise", alias, "solution")
    analysis_path = expected_path(arena_number, round_num, "revise", alias, "analysis")
    commit_desc = f"round {round_num:02d} revise {alias}"

    return REVISE_TEMPLATE.format(
        alias=alias,
        critiques_block=critiques_block,
        solution_path=solution_path,
        analysis_path=analysis_path,
        commit_block=_COMMIT_BLOCK.format(commit_desc=commit_desc),
    )
