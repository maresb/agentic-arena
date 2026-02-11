"""Phase implementations for the arena consensus loop.

2-phase design: Generate -> Evaluate (critique + vote).
Each round is a clean generate-then-evaluate pair.  Round 0 launches
agents; subsequent rounds send follow-ups with critique references.

Each phase function mutates the :class:`ArenaState` in place and
persists it after every meaningful step.  The orchestrator can be
killed and restarted at any point — previously completed work is
not re-done.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter
from collections.abc import Callable

from arena.api import (
    CursorCloudAPI,
    wait_for_all_agents,
    wait_for_all_followups,
    wait_for_followup,
)
from arena.extraction import (
    FILE_COMMIT_RETRY_PROMPT,
    extract_latest_response,
    parse_vote_verdict_json,
)
from arena.git import fetch_file_from_branch
from arena.prompts import (
    evaluate_prompt,
    generate_prompt,
)
from arena.state import (
    ArenaState,
    Phase,
    ProgressStatus,
    expected_path,
    resolve_model,
    save_state,
)

logger = logging.getLogger("arena")


def agent_label(alias: str, state: ArenaState) -> str:
    """Return a human-readable label like ``agent_a (opus)`` for log messages."""
    model = state.alias_mapping.get(alias)
    if model:
        return f"{alias} ({model})"
    return alias


def _record_timing_start(state: ArenaState, alias: str, phase_name: str) -> None:
    """Record the start time for an agent's phase."""
    if alias not in state.agent_timing:
        state.agent_timing[alias] = {}
    state.agent_timing[alias][phase_name] = {"start": time.time()}


def _record_timing_end(state: ArenaState, alias: str, phase_name: str) -> None:
    """Record the end time for an agent's phase."""
    if alias not in state.agent_timing:
        state.agent_timing[alias] = {}
    entry = state.agent_timing[alias].get(phase_name, {})
    entry["end"] = time.time()
    state.agent_timing[alias][phase_name] = entry


def _capture_agent_metadata(state: ArenaState, alias: str, api: CursorCloudAPI) -> None:
    """Capture metadata (summary, linesAdded, filesChanged) from status()."""
    agent_id = state.agent_ids.get(alias)
    if not agent_id:
        return
    try:
        info = api.status(agent_id)
        meta: dict[str, str | int] = {}
        for key in ("summary", "linesAdded", "filesChanged"):
            if key in info:
                meta[key] = info[key]
        if meta:
            state.agent_metadata[alias] = meta
    except Exception:
        logger.debug("Failed to capture metadata for %s", alias)


def _update_token_usage(
    state: ArenaState, alias: str, conversation: list[dict]
) -> None:
    """Update cumulative token usage for *alias* from conversation metadata."""
    total = 0
    for msg in conversation:
        usage = msg.get("usage", {})
        total += usage.get("total_tokens", 0)
    if total > 0:
        state.token_usage[alias] = total


def _saver(state: ArenaState, path: str) -> Callable[[], None]:
    """Return a zero-arg closure that persists *state* to *path*."""

    def _save() -> None:
        save_state(state, path)

    return _save


def _save_conversation(
    state: ArenaState,
    state_path: str,
    alias: str,
    conversation: list[dict],
) -> None:
    """Persist the full conversation transcript to disk.

    Writes to ``conversations/{model}.json`` under the arena directory
    (derived from *state_path*), using the model nickname rather than
    the alias.  Overwrites on each call so the file always reflects
    the latest state of the conversation.
    """
    arena_dir = os.path.dirname(state_path)
    conv_dir = os.path.join(arena_dir, "conversations")
    os.makedirs(conv_dir, exist_ok=True)
    model = state.alias_mapping.get(alias, alias)
    out_path = os.path.join(conv_dir, f"{model}.json")
    try:
        with open(out_path, "w") as f:
            json.dump(conversation, f, indent=2, ensure_ascii=False)
        logger.debug(
            "Saved conversation for %s (%d messages)", model, len(conversation)
        )
    except OSError:
        logger.warning("Failed to save conversation for %s to %s", model, out_path)


# ---------------------------------------------------------------------------
# File-based extraction helpers
# ---------------------------------------------------------------------------


def _fetch_agent_file(state: ArenaState, alias: str, file_path: str) -> str | None:
    """Fetch a file from an agent's branch. Returns content or None."""
    branch = state.branch_names.get(alias)
    if not branch:
        logger.debug("No branch name for %s; cannot fetch file", alias)
        return None
    return fetch_file_from_branch(state.config.repo, branch, file_path)


def _fetch_with_retry(
    state: ArenaState,
    alias: str,
    file_path: str,
    api: CursorCloudAPI,
    *,
    commit_desc: str,
    max_retries: int = 3,
) -> str | None:
    """Fetch a file from an agent's branch, re-prompting if missing.

    Retries up to *max_retries* times, sending a follow-up each time
    asking the agent to commit the expected file.  Returns the file
    content on success, or ``None`` if all retries are exhausted.
    """
    content = _fetch_agent_file(state, alias, file_path)
    if content is not None:
        return content

    branch = state.branch_names.get(alias)
    agent_id = state.agent_ids.get(alias)
    if not branch or not agent_id:
        return None

    for attempt in range(1, max_retries + 1):
        logger.warning(
            "File %s not found on %s branch (attempt %d/%d); re-prompting",
            file_path,
            agent_label(alias, state),
            attempt,
            max_retries,
        )
        prev_count = len(api.get_conversation(agent_id))
        api.followup(
            agent_id=agent_id,
            prompt=FILE_COMMIT_RETRY_PROMPT.format(
                expected_path=file_path,
                commit_desc=commit_desc,
            ),
        )
        wait_for_followup(api, agent_id, prev_count)

        content = _fetch_agent_file(state, alias, file_path)
        if content is not None:
            return content

    logger.error(
        "File %s not committed by %s after %d retries",
        file_path,
        agent_label(alias, state),
        max_retries,
    )
    return None


# ---------------------------------------------------------------------------
# Phase 1: Generate (parallel — initial solve or revision)
# ---------------------------------------------------------------------------


def step_generate(
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.yaml"
) -> None:
    """Generate solutions — launch agents (round 0) or revise (round > 0).

    Round 0: launch brand-new agents with the task prompt.
    Round > 0: send follow-up with critique references so agents revise.
    Both paths produce solution + analysis files.
    """
    _save = _saver(state, state_path)
    anum = state.config.arena_number
    rnd = state.round
    is_initial = rnd == 0

    # Build critique references for revision rounds
    agent_critique_files: list[tuple[str, str, str]] | None = None
    if not is_initial:
        agent_critique_files = []
        for a in state.alias_mapping:
            branch = state.branch_names.get(a, "")
            crit_path = expected_path(anum, a, "critique")
            agent_critique_files.append((a, branch, crit_path))

    if is_initial:
        # ── Round 0: Launch agents ──
        for alias, model in state.alias_mapping.items():
            if state.phase_progress.get(alias) == ProgressStatus.DONE:
                continue
            if alias not in state.agent_ids:
                logger.info("Launching %s", agent_label(alias, state))
                _record_timing_start(state, alias, "generate")
                agent = api.launch(
                    prompt=generate_prompt(state.config.task, alias, anum, rnd),
                    repo=state.config.repo,
                    ref=state.config.base_branch,
                    model=resolve_model(state, model),
                )
                state.agent_ids[alias] = agent["id"]
                launch_branch = agent.get("branchName") or agent.get("branch_name")
                if launch_branch:
                    state.branch_names[alias] = launch_branch
                _save()

        # Poll all pending agents until finished (truly parallel)
        pending = {
            alias: state.agent_ids[alias]
            for alias in state.alias_mapping
            if state.phase_progress.get(alias) != ProgressStatus.DONE
        }
        if pending:
            wait_for_all_agents(api, pending)

        # Capture branch names from the status() response
        for alias in state.alias_mapping:
            if alias in state.branch_names:
                continue
            agent_id = state.agent_ids.get(alias)
            if not agent_id:
                continue
            try:
                info = api.status(agent_id)
                branch = info.get("target", {}).get("branchName") or info.get(
                    "target", {}
                ).get("branch_name")
                if branch:
                    state.branch_names[alias] = branch
                    logger.info("%s branch: %s", agent_label(alias, state), branch)
            except Exception:
                logger.warning(
                    "Failed to fetch branch name for %s", agent_label(alias, state)
                )
        _save()
    else:
        # ── Round > 0: Send follow-ups with critique references ──
        for alias in state.alias_mapping:
            if state.phase_progress.get(alias) == ProgressStatus.DONE:
                continue

            if state.phase_progress.get(alias) == ProgressStatus.SENT:
                current_count = len(api.get_conversation(state.agent_ids[alias]))
                saved_count = state.sent_msg_counts.get(alias, 0)
                if current_count > saved_count:
                    continue
                logger.info(
                    "Re-sending generate follow-up to %s (crash recovery)",
                    agent_label(alias, state),
                )
            else:
                state.sent_msg_counts[alias] = len(
                    api.get_conversation(state.agent_ids[alias])
                )
                state.phase_progress[alias] = ProgressStatus.SENT
                _record_timing_start(state, alias, "generate")
                _save()
                logger.info(
                    "Sending generate follow-up to %s", agent_label(alias, state)
                )

            api.followup(
                agent_id=state.agent_ids[alias],
                prompt=generate_prompt(
                    state.config.task,
                    alias,
                    anum,
                    rnd,
                    agent_critique_files=agent_critique_files,
                ),
            )

        # Wait for all SENT agents
        pending_followups = {
            alias: (state.agent_ids[alias], state.sent_msg_counts.get(alias, 0))
            for alias in state.alias_mapping
            if state.phase_progress.get(alias) == ProgressStatus.SENT
        }
        if pending_followups:
            wait_for_all_followups(api, pending_followups)

    # ── Extract solutions from committed branch files ──
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue

        commit_desc = f"round {rnd:02d} generate {alias}"
        sol_path = expected_path(anum, alias, "solution")
        ana_path = expected_path(anum, alias, "analysis")

        solution = _fetch_with_retry(
            state, alias, sol_path, api, commit_desc=commit_desc
        )
        analysis = _fetch_agent_file(state, alias, ana_path)

        conversation = api.get_conversation(state.agent_ids[alias])
        _update_token_usage(state, alias, conversation)
        _save_conversation(state, state_path, alias, conversation)

        if solution is None:
            logger.error(
                "No solution from %s; agent did not commit %s",
                agent_label(alias, state),
                sol_path,
            )

        state.solutions[alias] = solution or ""
        state.analyses[alias] = analysis or ""
        state.phase_progress[alias] = ProgressStatus.DONE
        _record_timing_end(state, alias, "generate")
        _capture_agent_metadata(state, alias, api)
        _save()

    state.phase = Phase.EVALUATE
    state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
    state.sent_msg_counts = {}
    _save()


# ---------------------------------------------------------------------------
# Phase 2: Evaluate (parallel — critique + vote)
# ---------------------------------------------------------------------------


def step_evaluate(
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.yaml"
) -> None:
    """Each agent critiques all solutions and votes for the best.

    This phase combines the old evaluate + verify phases.  It produces
    both a critique (markdown) and a verdict (JSON) per agent.
    """
    _save = _saver(state, state_path)
    anum = state.config.arena_number
    rnd = state.round

    # Build branch file references for all agents (stable paths)
    agent_files: list[tuple[str, str, str, str]] = []
    for a in state.alias_mapping:
        branch = state.branch_names.get(a, "")
        sol_path = expected_path(anum, a, "solution")
        ana_path = expected_path(anum, a, "analysis")
        agent_files.append((a, branch, sol_path, ana_path))

    # Send follow-ups to all agents
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue

        if state.phase_progress.get(alias) == ProgressStatus.SENT:
            # Resume path: re-send if the agent never got the message
            current_count = len(api.get_conversation(state.agent_ids[alias]))
            saved_count = state.sent_msg_counts.get(alias, 0)
            if current_count > saved_count:
                continue  # Agent already received and may have replied
            logger.info(
                "Re-sending evaluate follow-up to %s (crash recovery)",
                agent_label(alias, state),
            )
        else:
            state.sent_msg_counts[alias] = len(
                api.get_conversation(state.agent_ids[alias])
            )
            state.phase_progress[alias] = ProgressStatus.SENT
            _record_timing_start(state, alias, "evaluate")
            _save()
            logger.info("Sending evaluate follow-up to %s", agent_label(alias, state))

        api.followup(
            agent_id=state.agent_ids[alias],
            prompt=evaluate_prompt(alias, agent_files, anum, rnd),
        )

    # Wait for all SENT agents
    pending = {
        alias: (state.agent_ids[alias], state.sent_msg_counts.get(alias, 0))
        for alias in state.alias_mapping
        if state.phase_progress.get(alias) == ProgressStatus.SENT
    }
    if pending:
        wait_for_all_followups(api, pending)

    # Extract critiques and verdicts
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue

        commit_desc = f"round {rnd:02d} evaluate {alias}"
        critique_path = expected_path(anum, alias, "critique")
        verdict_path = expected_path(anum, alias, "verdict", ext="json")

        # ── Critique extraction ──
        critique = _fetch_with_retry(
            state, alias, critique_path, api, commit_desc=commit_desc
        )

        # ── Verdict extraction ──
        verdict_text = _fetch_with_retry(
            state, alias, verdict_path, api, commit_desc=commit_desc
        )

        conversation = api.get_conversation(state.agent_ids[alias])
        _update_token_usage(state, alias, conversation)
        _save_conversation(state, state_path, alias, conversation)

        if critique is None:
            logger.error(
                "No critique from %s; agent did not commit %s",
                agent_label(alias, state),
                critique_path,
            )
        state.critiques[alias] = critique or ""

        if verdict_text is None:
            logger.error(
                "No verdict from %s; agent did not commit %s",
                agent_label(alias, state),
                verdict_path,
            )

        valid_aliases = frozenset(state.alias_mapping)
        verdict = parse_vote_verdict_json(
            verdict_text or "", valid_aliases=valid_aliases
        )

        # Strip self-votes silently
        if alias in verdict.best_solutions:
            logger.info("Stripping self-vote from %s", agent_label(alias, state))
            verdict.best_solutions = [a for a in verdict.best_solutions if a != alias]

        state.verify_votes[alias] = verdict.best_solutions
        if verdict.convergence_score is not None:
            state.verify_scores[alias] = verdict.convergence_score
        state.verify_divergences[alias] = [d.model_dump() for d in verdict.divergences]

        state.phase_progress[alias] = ProgressStatus.DONE
        _record_timing_end(state, alias, "evaluate")
        _save()

    # ── Accumulate verdict text for history ──
    verdict_summary = json.dumps(
        {
            "votes": state.verify_votes,
            "scores": state.verify_scores,
            "divergences": state.verify_divergences,
            "token_usage": dict(state.token_usage),
        },
        indent=2,
    )
    state.verdict_history.append(verdict_summary)

    # ── Consensus check ──
    n_agents = len(state.alias_mapping)
    scores = list(state.verify_scores.values())
    final_score = min(scores) if scores else 0

    # Tally votes
    all_votes: list[str] = []
    for votes in state.verify_votes.values():
        all_votes.extend(votes)
    vote_tally = Counter(all_votes)

    # Check for winner: needs N-1 votes (all non-author agents)
    winner = None
    for candidate, count in vote_tally.most_common():
        if count >= n_agents - 1:
            winner = candidate
            break

    consensus = final_score >= 9 and winner is not None

    logger.info(
        "Vote results: scores=%s, tally=%s, final_score=%d, winner=%s, consensus=%s",
        state.verify_scores,
        dict(vote_tally),
        final_score,
        winner,
        consensus,
    )

    # ── Optional verify commands (only when consensus reached) ──
    if consensus and state.config.verify_commands:
        verify_failed = False
        state.verify_results = []
        # Run verify commands via the winning agent
        verify_agent_alias = winner
        verify_agent_id = state.agent_ids.get(verify_agent_alias or "")

        if verify_agent_id:
            for cmd in state.config.verify_commands:
                cmd_prev_count = len(api.get_conversation(verify_agent_id))
                logger.info(
                    "Running verify command via %s: %s", verify_agent_alias, cmd
                )
                api.followup(
                    agent_id=verify_agent_id,
                    prompt=f"Run this command and report the result: {cmd}",
                )
                wait_for_followup(api, verify_agent_id, cmd_prev_count)
                cmd_conversation = api.get_conversation(verify_agent_id)
                cmd_result = extract_latest_response(cmd_conversation)
                state.verify_results.append(cmd_result)
                _save()
                lower = cmd_result.lower()
                if any(
                    kw in lower for kw in ("fail", "error", "exception", "exit code")
                ):
                    verify_failed = True
                    logger.warning("Verify command '%s' appears to have failed", cmd)

            if verify_failed and state.config.verify_mode == "gating":
                logger.warning(
                    "Verify commands failed in gating mode; overriding consensus"
                )
                consensus = False

    # ── Determine next phase ──
    if consensus:
        state.phase = Phase.DONE
        state.completed = True
        state.consensus_reached = True
        state.verify_winner = winner
        state.final_verdict = verdict_summary
    elif state.round >= state.config.max_rounds:
        state.phase = Phase.DONE
        state.completed = True
        state.consensus_reached = False
        state.final_verdict = verdict_summary
    else:
        state.final_verdict = verdict_summary
        state.round += 1
        state.phase = Phase.GENERATE
        state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
        # Clear per-round transient state for the next generate phase
        state.critiques = {}
        state.verify_votes = {}
        state.verify_scores = {}
        state.verify_divergences = {}
        state.verify_winner = None
        state.verify_results = []

    state.sent_msg_counts = {}
    _save()
