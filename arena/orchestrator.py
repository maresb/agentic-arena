"""Main orchestrator loop and report generation.

The orchestrator is a simple FSM: generate -> evaluate, looping back
to generate until consensus or max rounds.  All progress lives in the
state file, so the process can be killed and restarted at any point.

The core primitive is :func:`step_once`, which executes exactly one phase
transition.  :func:`run_orchestrator` is a convenience wrapper that loops
``step_once`` until the arena is complete.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from arena.api import CursorCloudAPI
from arena.phases import step_evaluate, step_generate
from arena.state import (
    PHASE_NUMBERS,
    ArenaState,
    Phase,
    ProgressStatus,
    load_state,
    sanitize_filename_component,
    save_state,
)

ARENAS_ROOT = "arenas"


def _ensure_gitignore(root: str) -> None:
    """Create a .gitignore in *root* with ``*`` if it doesn't exist."""
    gitignore = os.path.join(root, ".gitignore")
    if not os.path.exists(gitignore):
        os.makedirs(root, exist_ok=True)
        with open(gitignore, "w") as f:
            f.write("*\n")


def next_arena_dir(root: str = ARENAS_ROOT) -> str:
    """Return the path for the next sequentially-numbered arena directory.

    Scans *root* for existing ``NNNN`` subdirectories and returns
    ``root/NNNN+1``.  Creates the *root* directory (and ``.gitignore``)
    if needed.
    """
    _ensure_gitignore(root)
    existing = sorted(
        int(d) for d in (os.listdir(root) if os.path.isdir(root) else []) if d.isdigit()
    )
    next_num = (existing[-1] + 1) if existing else 1
    return os.path.join(root, f"{next_num:04d}")


def latest_arena_dir(root: str = ARENAS_ROOT) -> str | None:
    """Return the most recent arena directory, or ``None`` if none exist."""
    if not os.path.isdir(root):
        return None
    numbered = sorted((int(d), d) for d in os.listdir(root) if d.isdigit())
    if not numbered:
        return None
    return os.path.join(root, numbered[-1][1])


def arena_number_from_dir(arena_dir: str) -> int:
    """Extract the NNNN number from an arena directory path.

    Returns 1 if the directory name is not a valid number.
    """
    basename = os.path.basename(arena_dir.rstrip("/"))
    try:
        return int(basename)
    except ValueError:
        return 1


logger = logging.getLogger("arena")

# ---------------------------------------------------------------------------
# Phase dispatch table
# ---------------------------------------------------------------------------

PHASE_HANDLERS = {
    Phase.GENERATE: step_generate,
    Phase.EVALUATE: step_evaluate,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api() -> CursorCloudAPI:
    """Create a :class:`CursorCloudAPI` from the ``CURSOR_API_KEY`` env var."""
    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CURSOR_API_KEY environment variable is not set. "
            "Export your Cursor API key to proceed."
        )
    return CursorCloudAPI(api_key)


def _content_uid(content: str) -> str:
    """Return a short deterministic UID from content (first 6 hex chars of SHA-256)."""
    return hashlib.sha256(content.encode()).hexdigest()[:6]


def _archive_artifact(arena_dir: str, name: str, content: str) -> None:
    """Write an artifact file, skipping if it already exists (deduplication)."""
    path = os.path.join(arena_dir, name)
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _archive_round(state: ArenaState, arena_dir: str) -> None:
    """Archive the current round's outputs using deterministic naming.

    Naming scheme:
    ``{round:02d}-{phase_number}-{phase_name}-{model}-{artifact_type}-{uid}.{ext}``

    Uses model names as identity (vs aliases in agent-committed files).
    *uid* is derived from content (SHA-256 prefix) for deduplication.
    Files already present on disk are not overwritten.
    """
    rnd = state.round
    gen_num = PHASE_NUMBERS["generate"]

    for alias in state.alias_mapping:
        model = sanitize_filename_component(
            str(state.alias_mapping.get(alias, "unknown"))
        )

        solution = state.solutions.get(alias)
        if solution:
            uid = _content_uid(solution)
            name = f"{rnd:02d}-{gen_num}-generate-{model}-solution-{uid}.md"
            _archive_artifact(arena_dir, name, solution)

        analysis = state.analyses.get(alias)
        if analysis:
            uid = _content_uid(analysis)
            name = f"{rnd:02d}-{gen_num}-generate-{model}-analysis-{uid}.md"
            _archive_artifact(arena_dir, name, analysis)

        critique = state.critiques.get(alias)
        if critique:
            uid = _content_uid(critique)
            eval_num = PHASE_NUMBERS["evaluate"]
            name = f"{rnd:02d}-{eval_num}-evaluate-{model}-critique-{uid}.md"
            _archive_artifact(arena_dir, name, critique)

        # Archive per-agent verdict
        votes = state.verify_votes.get(alias)
        score = state.verify_scores.get(alias)
        divergences = state.verify_divergences.get(alias, [])
        if votes is not None or score is not None:
            verdict_data: dict = {
                "convergence_score": score,
                "best_solutions": votes or [],
                "divergences": divergences,
            }
            verdict_json = json.dumps(verdict_data, indent=2)
            uid = _content_uid(verdict_json)
            eval_num = PHASE_NUMBERS["evaluate"]
            name = f"{rnd:02d}-{eval_num}-evaluate-{model}-verdict-{uid}.json"
            _archive_artifact(arena_dir, name, verdict_json)


def _archive_filename(
    rnd: int,
    phase_name: str,
    model: str,
    artifact: str,
    content: str,
    ext: str = "md",
) -> str:
    """Build the deterministic archive filename for a given artifact."""
    phase_num = PHASE_NUMBERS.get(phase_name, 0)
    uid = _content_uid(content)
    return f"{rnd:02d}-{phase_num}-{phase_name}-{model}-{artifact}-{uid}.{ext}"


# ---------------------------------------------------------------------------
# Rolling report
# ---------------------------------------------------------------------------


def _mermaid_vote_graph(
    aliases: list[str],
    alias_mapping: dict[str, str],
    scores: dict,
    votes: dict,
) -> list[str]:
    """Build a mermaid directed graph showing votes for one evaluate round.

    Returns a list of lines (including the fenced code block markers).
    Each node has three lines: alias (bold), model, and score.
    Edges are bare arrows from voter to votee.
    """
    lines: list[str] = ["```mermaid", "graph"]

    # Node declarations with multi-line markdown labels
    for alias in aliases:
        model = str(alias_mapping.get(alias, "unknown"))
        score = scores.get(alias, "—")
        # Mermaid markdown string: backtick-delimited, literal newlines
        lines.append(f'    {alias}["`**{alias}**')
        lines.append(f"{model}")
        lines.append(f'Score: {score}`"]')

    # Vote edges (bare arrows, no labels)
    for alias in aliases:
        for votee in votes.get(alias, []):
            if votee in alias_mapping:
                lines.append(f"    {alias} --> {votee}")

    lines.append("```")
    return lines


def update_report(state: ArenaState, arena_dir: str) -> None:
    """Regenerate ``report.md`` from the current state.

    Called after every phase so the report is always current.  The report
    is compact — metadata, per-round score tables, and hyperlinks to
    archived files.  No solution text is inlined.
    """
    lines: list[str] = []
    consensus = state.consensus_reached
    task_abbrev = state.config.task[:120] + (
        "…" if len(state.config.task) > 120 else ""
    )

    # ── Header ──
    lines += [
        "# Arena Report",
        "",
        f"**Task:** {task_abbrev}",
        f"**Round:** {state.round}",
        f"**Phase:** {state.phase.value}",
        f"**Completed:** {'Yes' if state.completed else 'No'}",
    ]
    if consensus is not None:
        lines.append(f"**Consensus:** {'Yes' if consensus else 'No'}")
    if state.verify_winner:
        winner_model = state.alias_mapping.get(state.verify_winner, "unknown")
        lines.append(f"**Winner:** {state.verify_winner} ({winner_model})")
    lines += ["", "### Agents", ""]
    lines.append("| Alias | Model |")
    lines.append("|-------|-------|")
    for alias in state.alias_mapping:
        model = state.alias_mapping.get(alias, "unknown")
        lines.append(f"| {alias} | {model} |")
    lines += ["", "---", ""]

    # ── Per-round sections (built from verdict_history) ──
    prev_tokens: dict[str, int] = {}

    for rnd_idx, vh_json in enumerate(state.verdict_history):
        try:
            vh = json.loads(vh_json) if isinstance(vh_json, str) else vh_json
        except (json.JSONDecodeError, TypeError):
            vh = {}

        rnd_votes: dict = vh.get("votes", {})
        rnd_scores: dict = vh.get("scores", {})
        rnd_divergences: dict = vh.get("divergences", {})
        rnd_tokens: dict[str, int] = vh.get("token_usage", {})

        scores_list = list(rnd_scores.values())
        final_score = min(scores_list) if scores_list else 0

        # Compute per-round token deltas
        token_deltas: dict[str, int] = {}
        for alias in state.alias_mapping:
            cur = rnd_tokens.get(alias, 0)
            prev = prev_tokens.get(alias, 0)
            if cur > 0:
                token_deltas[alias] = cur - prev

        lines.append(f"## Round {rnd_idx}")
        lines.append("")

        # Score/vote table (include token delta column if data exists)
        has_tokens = bool(token_deltas)
        if has_tokens:
            lines.append("| Agent | Model | Score | Voted for | Divergences | Tokens |")
            lines.append("|-------|-------|------:|-----------|-------------|-------:|")
        else:
            lines.append("| Agent | Model | Score | Voted for | Divergences |")
            lines.append("|-------|-------|------:|-----------|-------------|")
        for alias in state.alias_mapping:
            model = str(state.alias_mapping.get(alias, "unknown"))
            score = rnd_scores.get(alias, "—")
            votes = ", ".join(rnd_votes.get(alias, []))
            divs = rnd_divergences.get(alias, [])
            div_count = len(divs) if isinstance(divs, list) else 0
            if has_tokens:
                delta = token_deltas.get(alias, 0)
                lines.append(
                    f"| {alias} | {model} | {score} | {votes} "
                    f"| {div_count} | {delta:,} |"
                )
            else:
                lines.append(f"| {alias} | {model} | {score} | {votes} | {div_count} |")
        lines.append("")
        lines.append(f"**Min score:** {final_score}")
        lines.append("")

        # Mermaid vote diagram
        aliases = list(state.alias_mapping.keys())
        mermaid_lines = _mermaid_vote_graph(
            aliases, dict(state.alias_mapping), rnd_scores, rnd_votes
        )
        lines.extend(mermaid_lines)
        lines.append("")

        # Carry forward token snapshot for next round's delta
        if rnd_tokens:
            prev_tokens = dict(rnd_tokens)

        # Divergence details (if any)
        all_divs = [
            (alias, d)
            for alias in state.alias_mapping
            for d in (
                rnd_divergences.get(alias, [])
                if isinstance(rnd_divergences.get(alias), list)
                else []
            )
        ]
        if all_divs:
            lines.append("<details><summary>Divergences</summary>")
            lines.append("")
            for alias, d in all_divs:
                topic = d.get("topic", "?") if isinstance(d, dict) else "?"
                desc = d.get("description", "") if isinstance(d, dict) else str(d)
                lines.append(f"- **{alias}** — *{topic}*: {desc}")
            lines.append("")
            lines.append("</details>")
            lines.append("")

        # Archive file links
        lines.append("<details><summary>Archived files</summary>")
        lines.append("")
        for alias in state.alias_mapping:
            model_san = sanitize_filename_component(
                str(state.alias_mapping.get(alias, "unknown"))
            )
            gen_phase = "generate"

            link_parts: list[str] = []

            solution = state.solutions.get(alias)
            if solution:
                fname = _archive_filename(
                    rnd_idx, gen_phase, model_san, "solution", solution
                )
                link_parts.append(f"[solution]({fname})")

            analysis = state.analyses.get(alias)
            if analysis:
                fname = _archive_filename(
                    rnd_idx, gen_phase, model_san, "analysis", analysis
                )
                link_parts.append(f"[analysis]({fname})")

            critique = state.critiques.get(alias)
            if critique:
                fname = _archive_filename(
                    rnd_idx, "evaluate", model_san, "critique", critique
                )
                link_parts.append(f"[critique]({fname})")

            v_votes = rnd_votes.get(alias)
            v_score = rnd_scores.get(alias)
            if v_votes is not None or v_score is not None:
                divs = rnd_divergences.get(alias, [])
                verdict_data: dict = {
                    "convergence_score": v_score,
                    "best_solutions": v_votes or [],
                    "divergences": divs,
                }
                verdict_str = json.dumps(verdict_data, indent=2)
                fname = _archive_filename(
                    rnd_idx, "evaluate", model_san, "verdict", verdict_str, ext="json"
                )
                link_parts.append(f"[verdict]({fname})")

            if link_parts:
                links = " · ".join(link_parts)
                lines.append(f"- **{alias}** ({model_san}): {links}")

        lines.append("")
        lines.append("</details>")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Current voting results (for the live/latest round) ──
    if state.verify_scores and not state.verdict_history:
        # Edge case: scores exist but no verdict_history entry yet
        lines.append("## Current Voting")
        lines.append("")
        for alias in state.alias_mapping:
            model = state.alias_mapping.get(alias, "unknown")
            cur_score = state.verify_scores.get(alias, "—")
            cur_votes = state.verify_votes.get(alias, [])
            lines.append(
                f"- **{alias}** ({model}): score={cur_score}, voted for {cur_votes}"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── PR link ──
    if state.consensus_reached and state.branch_names and state.verify_winner:
        winner_alias = state.verify_winner
        if winner_alias in state.branch_names:
            branch = state.branch_names[winner_alias]
            repo = state.config.repo
            repo_url = (
                repo if repo.startswith("https://") else f"https://github.com/{repo}"
            )
            pr_url = (
                f"{repo_url}/compare/{state.config.base_branch}...{branch}?expand=1"
            )
            lines.append(f"**[Create PR for winner]({pr_url})**")
            lines.append("")
            lines.append("---")
            lines.append("")

    # ── Token usage ──
    if state.token_usage:
        cost_per_1k: dict[str, float] = {
            "opus": 0.075,
            "gpt": 0.060,
            "gemini": 0.035,
        }
        lines.append("## Token Usage")
        lines.append("")
        total_cost = 0.0
        for alias, tokens in state.token_usage.items():
            model = str(state.alias_mapping.get(alias, "unknown"))
            rate = cost_per_1k.get(model, 0.05)
            cost = (tokens / 1000) * rate
            total_cost += cost
            lines.append(f"- **{alias}** ({model}): {tokens:,} tokens (~${cost:.2f})")
        lines.append(
            f"- **Total**: {sum(state.token_usage.values()):,} tokens "
            f"(~${total_cost:.2f})"
        )
        lines.append("")

    report_path = os.path.join(arena_dir, "report.md")
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    logger.info("Report updated: %s", report_path)


# ---------------------------------------------------------------------------
# Winning solution
# ---------------------------------------------------------------------------


def _write_winning_solution(state: ArenaState, arena_dir: str) -> None:
    """Write ``winning-solution.md`` with the winner's final output.

    Only called when the arena is complete and a winner has been elected.
    """
    winner = state.verify_winner
    if not winner:
        return

    model = state.alias_mapping.get(winner, "unknown")
    scores = list(state.verify_scores.values())
    final_score = min(scores) if scores else 0

    lines = [
        "# Winning Solution",
        "",
        f"**Winner:** {winner} ({model})",
        f"**Final consensus score:** {final_score}",
        f"**Rounds:** {state.round}",
    ]

    # PR link
    if state.branch_names and winner in state.branch_names:
        branch = state.branch_names[winner]
        repo = state.config.repo
        repo_url = repo if repo.startswith("https://") else f"https://github.com/{repo}"
        pr_url = f"{repo_url}/compare/{state.config.base_branch}...{branch}?expand=1"
        lines.append(f"**PR:** {pr_url}")

    lines += ["", "---", ""]

    solution = state.solutions.get(winner, "")
    if solution:
        lines += ["## Solution", "", solution, ""]

    analysis = state.analyses.get(winner, "")
    if analysis:
        lines += ["---", "", "## Analysis", "", analysis, ""]

    path = os.path.join(arena_dir, "winning-solution.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    logger.info("Winning solution written to %s", path)


# ---------------------------------------------------------------------------
# Legacy wrapper
# ---------------------------------------------------------------------------


def generate_final_report(state: ArenaState, arena_dir: str) -> None:
    """Generate report and winning solution at arena completion.

    Kept for backward compatibility.  New code should call
    :func:`update_report` (rolling) and :func:`_write_winning_solution`
    directly.
    """
    update_report(state, arena_dir)
    _write_winning_solution(state, arena_dir)


def reopen_arena(state: ArenaState) -> None:
    """Reset a completed arena so it can run another generate-evaluate cycle.

    Increments the round counter, sets the phase to GENERATE, and clears
    all per-round transient state and completion flags.  The caller is
    responsible for persisting the state afterwards.
    """
    state.completed = False
    state.consensus_reached = None
    state.final_verdict = None
    state.round += 1
    state.phase = Phase.GENERATE
    state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
    state.sent_msg_counts = {}
    # Clear per-round transient state
    state.critiques = {}
    state.verify_votes = {}
    state.verify_scores = {}
    state.verify_divergences = {}
    state.verify_winner = None
    state.verify_results = []


PENDING_COMMENTS_FILE = "pending-comments.json"

OPERATOR_WRAP_TEMPLATE = (
    "The arena operator has provided additional context for your current task:\n\n"
    "{message}"
)


def deliver_pending_comments(
    state: ArenaState, arena_dir: str, api: CursorCloudAPI
) -> int:
    """Deliver any queued operator comments from the sidecar file.

    Reads ``pending-comments.json`` from *arena_dir*, fires all follow-ups
    in parallel, waits for all responses, then saves conversations.
    Deletes the sidecar file after successful delivery.

    Returns the number of comments delivered.
    """
    from arena.api import wait_for_all_followups  # avoid circular at module level

    sidecar = os.path.join(arena_dir, PENDING_COMMENTS_FILE)
    if not os.path.exists(sidecar):
        return 0

    with open(sidecar) as f:
        try:
            comments = json.load(f)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Malformed %s — skipping", PENDING_COMMENTS_FILE)
            return 0

    if not isinstance(comments, list) or not comments:
        return 0

    state_path = os.path.join(arena_dir, "state.yaml")

    # Fire all follow-ups, collecting prev_counts for parallel waiting
    pending: dict[str, tuple[str, int]] = {}  # alias -> (agent_id, prev_count)
    delivered = 0

    for entry in comments:
        message: str = entry.get("message", "")
        if not message:
            continue
        wrapped: bool = entry.get("wrapped", True)
        targets: list[str] = entry.get("targets", list(state.alias_mapping))

        if wrapped:
            message = OPERATOR_WRAP_TEMPLATE.format(message=message)

        for alias in targets:
            agent_id = state.agent_ids.get(alias)
            if not agent_id:
                logger.warning("Cannot deliver comment to %s — no agent_id", alias)
                continue
            prev_count = len(api.get_conversation(agent_id))
            logger.info("Delivering operator comment to %s", alias)
            api.followup(agent_id=agent_id, prompt=message)
            pending[alias] = (agent_id, prev_count)

        delivered += 1

    # Wait for all agents in parallel
    if pending:
        wait_for_all_followups(api, pending)

    # Save conversations after all deliveries complete
    from arena.phases import _save_conversation, _update_token_usage

    for alias, (agent_id, _prev_count) in pending.items():
        conversation = api.get_conversation(agent_id)
        _update_token_usage(state, alias, conversation)
        _save_conversation(state, state_path, alias, conversation)

    # Remove sidecar after all comments are delivered
    try:
        os.remove(sidecar)
    except OSError:
        pass

    if delivered:
        logger.info("Delivered %d queued operator comment(s)", delivered)
        save_state(state, state_path)

    return delivered


def step_once(arena_dir: str = ARENAS_ROOT) -> ArenaState:
    """Execute exactly one phase transition and return the updated state."""
    state_path = os.path.join(arena_dir, "state.yaml")
    state = load_state(state_path)
    if state is None:
        raise FileNotFoundError(
            f"No state file found at {state_path}. "
            "Use 'python -m arena init' to create one."
        )
    if state.completed:
        raise RuntimeError("Arena is already completed.")

    before_phase = state.phase
    handler = PHASE_HANDLERS.get(before_phase)
    if handler is None:
        raise ValueError(f"Unknown or terminal phase: {before_phase}")

    api = _make_api()

    # Deliver any queued operator comments before the phase runs
    deliver_pending_comments(state, arena_dir, api)

    logger.info("=== Round %d | Phase: %s ===", state.round, before_phase)
    handler(state, api, state_path=state_path)

    _archive_round(state, arena_dir)
    update_report(state, arena_dir)
    if state.completed:
        _write_winning_solution(state, arena_dir)
    save_state(state, state_path)
    return state


def run_orchestrator(arena_dir: str = ARENAS_ROOT) -> None:
    """Loop :func:`step_once` until the arena is complete, then report."""
    while True:
        state = step_once(arena_dir)
        if state.completed:
            break

    consensus = (
        state.consensus_reached
        if state.consensus_reached is not None
        else state.final_verdict is not None
    )
    alias_display = {k: str(v) for k, v in state.alias_mapping.items()}
    print(f"Arena complete. Rounds: {state.round}.")
    print(
        f"Verdict: {'Consensus reached' if consensus else 'No consensus (max rounds)'}"
    )
    print(f"Alias mapping: {alias_display}")
