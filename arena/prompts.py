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
# Generate phase (phase 1) — initial solve or revision
# ---------------------------------------------------------------------------

GENERATE_TEMPLATE = """\
You are {alias}. {task}
{critiques_block}
After completing your work, commit your structured response as two files:
  {solution_path}
  {analysis_path}

{solution_path} should contain:
  ## PLAN — Numbered key decisions with rationale.
  ## CHANGES — Unified diff or precise change descriptions.

{analysis_path} should contain:
  ## RISKS — Known risks, edge cases, trade-offs.
  ## OPEN QUESTIONS — Uncertainties requiring verification.{disagreements_block}
{commit_block}"""


def generate_prompt(
    task: str,
    alias: str,
    arena_number: int,
    round_num: int,
    agent_critique_files: list[tuple[str, str, str]] | None = None,
) -> str:
    """Generate the prompt for the generate phase.

    Round 0 (no critiques): produces the initial solve prompt.
    Round > 0 (with critiques): produces the revision prompt with
    branch references to all agents' critiques.
    """
    solution_path = expected_path(arena_number, alias, "solution")
    analysis_path = expected_path(arena_number, alias, "analysis")
    commit_desc = f"round {round_num:02d} generate {alias}"

    # Build critiques block (empty for round 0)
    if agent_critique_files:
        shuffled = list(agent_critique_files)
        random.shuffle(shuffled)
        ref_blocks = []
        for crit_alias, branch, crit_path in shuffled:
            label = crit_alias.replace("_", " ").upper()
            ref_blocks.append(
                f"=== CRITIQUE BY {label} ===\n"
                f"  Branch: {branch}\n"
                f"  Critique: git show origin/{branch}:{crit_path}"
            )
        critiques_block = (
            "\nRead all agents' critiques by fetching them from their branches. "
            "Use `git show` to read each file:\n\n"
            + "\n\n".join(ref_blocks)
            + "\n\nRead ALL critiques listed above before writing your revised solution.\n\n"
            "Produce your REVISED solution, incorporating the strongest elements "
            "from the feedback.\n"
        )
        disagreements_block = (
            "\n  ## DISAGREEMENTS — Any remaining substantive disagreements\n"
            '  with the other approaches, or "None."'
        )
    else:
        critiques_block = ""
        disagreements_block = ""

    return GENERATE_TEMPLATE.format(
        alias=alias,
        task=task,
        critiques_block=critiques_block,
        solution_path=solution_path,
        analysis_path=analysis_path,
        disagreements_block=disagreements_block,
        commit_block=_COMMIT_BLOCK.format(commit_desc=commit_desc),
    )


# ---------------------------------------------------------------------------
# Evaluate phase (phase 2 — critique + vote)
# ---------------------------------------------------------------------------

EVALUATE_TEMPLATE = """\
You are {alias}. Read the solutions and analyses from all agents by
fetching them from their branches. Use `git show` to read each file:

{references_block}

Read ALL files listed above before writing your critique.

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
  "best_solutions": [<aliases exactly as written (e.g. "agent_a"), excluding your own ({alias}), at least one required>],
  "divergences": [
    {{"topic": "<short label>", "description": "<what specifically differs and between whom>"}}
  ],
  "rationale": "<why these solutions are best / what still differs>"
}}

SCORING RULES (strictly enforced):
- If your divergences list is EMPTY, your score MUST be 10.
- If your divergences list is NON-EMPTY, your score MUST be 9 or lower.
- Each divergence must be specific and actionable — not vague.

Vote for the best solution(s) OTHER than your own.

Commit both files:
  {critique_path}
  {verdict_path}
{commit_block}"""


def evaluate_prompt(
    alias: str,
    agent_files: list[tuple[str, str, str, str]],
    arena_number: int,
    round_num: int,
) -> str:
    """Generate the evaluate prompt with branch file references.

    Parameters
    ----------
    alias:
        The alias of the agent receiving this prompt.
    agent_files:
        List of (alias, branch, solution_path, analysis_path) tuples
        for ALL agents.
    """
    shuffled = list(agent_files)
    random.shuffle(shuffled)

    ref_blocks = []
    for ref_alias, branch, sol_path, ana_path in shuffled:
        label = ref_alias.replace("_", " ").upper()
        ref_blocks.append(
            f"=== {label} ===\n"
            f"  Branch: {branch}\n"
            f"  Solution: git show origin/{branch}:{sol_path}\n"
            f"  Analysis: git show origin/{branch}:{ana_path}"
        )
    references_block = "\n\n".join(ref_blocks)

    critique_path = expected_path(arena_number, alias, "critique")
    verdict_path = expected_path(arena_number, alias, "verdict", ext="json")
    commit_desc = f"round {round_num:02d} evaluate {alias}"

    return EVALUATE_TEMPLATE.format(
        alias=alias,
        references_block=references_block,
        critique_path=critique_path,
        verdict_path=verdict_path,
        commit_block=_COMMIT_BLOCK.format(commit_desc=commit_desc),
    )
