"""Phase implementations for the arena consensus loop.

Each phase function mutates the :class:`ArenaState` in place and persists it
after every meaningful step. The orchestrator can be killed and restarted
at any point — previously completed work is not re-done.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from arena.api import (
    CursorCloudAPI,
    wait_for_all_agents,
    wait_for_all_followups,
    wait_for_followup,
)
from arena.extraction import (
    RETRY_PROMPT,
    VERDICT_RETRY_PROMPT,
    VerdictDecision,
    extract_latest_response,
    extract_solution_and_analysis,
    extract_xml_section,
    parse_verdict,
)
from arena.prompts import (
    MODELS,
    evaluate_prompt,
    revise_prompt,
    solve_prompt,
    verify_prompt,
)
from arena.state import ArenaState, Phase, ProgressStatus, save_state

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


def _capture_agent_metadata(
    state: ArenaState, alias: str, api: CursorCloudAPI
) -> None:
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


def _extract_with_retry(
    api: CursorCloudAPI,
    agent_id: str,
    conversation: list[dict],
    *,
    max_retries: int = 1,
) -> tuple[str, str]:
    """Extract solution/analysis, re-prompting once if XML tags are missing.

    If the initial extraction falls back to using the full response (no
    ``<solution>`` tag found), sends :data:`RETRY_PROMPT` as a follow-up
    and tries again.  Returns the best available result even if the retry
    also fails.
    """
    solution, analysis = extract_solution_and_analysis(conversation)

    for attempt in range(max_retries):
        # If the solution tag was found, we're good
        text = conversation[-1].get("content") or conversation[-1].get("text", "")
        if extract_xml_section(text, "solution") is not None:
            break

        logger.warning(
            "No <solution> tag in agent %s response (attempt %d/%d), re-prompting",
            agent_id,
            attempt + 1,
            max_retries,
        )
        prev_count = len(conversation)
        api.followup(agent_id=agent_id, prompt=RETRY_PROMPT)
        wait_for_followup(api, agent_id, prev_count)
        conversation = api.get_conversation(agent_id)
        solution, analysis = extract_solution_and_analysis(conversation)

    return solution, analysis


# ---------------------------------------------------------------------------
# Phase 1: Solve (parallel)
# ---------------------------------------------------------------------------


def step_solve(
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.yaml"
) -> None:
    """Launch agents to solve the task independently in parallel."""
    _save = _saver(state, state_path)

    # Launch agents that haven't started yet
    for alias, model in state.alias_mapping.items():
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue
        if alias not in state.agent_ids:
            logger.info("Launching %s", agent_label(alias, state))
            _record_timing_start(state, alias, "solve")
            agent = api.launch(
                prompt=solve_prompt(state.config.task),
                repo=state.config.repo,
                ref=state.config.base_branch,
                model=MODELS.get(model, model),
            )
            state.agent_ids[alias] = agent["id"]
            # Capture branch name if returned by the API
            branch = agent.get("branchName") or agent.get("branch_name")
            if branch:
                state.branch_names[alias] = branch
            _save()

    # Poll all pending agents until finished (truly parallel)
    pending = {
        alias: state.agent_ids[alias]
        for alias in state.alias_mapping
        if state.phase_progress.get(alias) != ProgressStatus.DONE
    }
    if pending:
        wait_for_all_agents(api, pending)

    # Capture branch names from the status() response now that agents
    # have finished.  The launch() response doesn't include branch names,
    # but status() returns target.branchName once the agent has created
    # its working branch.  (arena-run-summary2 issue #4 / fix #3)
    for alias in state.alias_mapping:
        if alias in state.branch_names:
            continue  # Already have it (e.g. from a previous run)
        agent_id = state.agent_ids.get(alias)
        if not agent_id:
            continue
        try:
            info = api.status(agent_id)
            branch = (
                info.get("target", {}).get("branchName")
                or info.get("target", {}).get("branch_name")
            )
            if branch:
                state.branch_names[alias] = branch
                logger.info("%s branch: %s", agent_label(alias, state), branch)
        except Exception:
            logger.warning("Failed to fetch branch name for %s", agent_label(alias, state))
    _save()

    # Extract content from all finished agents (with retry on missing tags)
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue
        conversation = api.get_conversation(state.agent_ids[alias])
        _update_token_usage(state, alias, conversation)
        solution, analysis = _extract_with_retry(
            api, state.agent_ids[alias], conversation
        )
        state.solutions[alias] = solution
        state.analyses[alias] = analysis
        state.phase_progress[alias] = ProgressStatus.DONE
        _record_timing_end(state, alias, "solve")
        _capture_agent_metadata(state, alias, api)
        _save()

    state.phase = Phase.EVALUATE
    state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
    state.sent_msg_counts = {}
    _save()


# ---------------------------------------------------------------------------
# Phase 2: Evaluate (parallel)
# ---------------------------------------------------------------------------


def step_evaluate(
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.yaml"
) -> None:
    """Each agent critiques the other two solutions without revising its own."""
    _save = _saver(state, state_path)

    # Send all follow-ups, persisting message counts for resume safety.
    # On resume, re-send to SENT agents whose message count hasn't changed
    # (crash between persisting SENT and the actual POST).
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue

        if state.config.branch_only and state.branch_names:
            others = [
                (k, "(See branch — use git fetch to inspect)")
                for k in state.solutions
                if k != alias
            ]
        else:
            others = [(k, v) for k, v in state.solutions.items() if k != alias]
        random.shuffle(others)  # Presentation-order neutrality

        if state.phase_progress.get(alias) == ProgressStatus.SENT:
            # Resume path: re-send if the agent never got the message
            current_count = len(api.get_conversation(state.agent_ids[alias]))
            saved_count = state.sent_msg_counts.get(alias, 0)
            if current_count > saved_count:
                continue  # Agent already received and may have replied
            logger.info("Re-sending evaluate follow-up to %s (crash recovery)", agent_label(alias, state))
        else:
            state.sent_msg_counts[alias] = len(
                api.get_conversation(state.agent_ids[alias])
            )
            state.phase_progress[alias] = ProgressStatus.SENT
            _record_timing_start(state, alias, "evaluate")
            _save()  # Persist count BEFORE sending to survive crash
            logger.info("Sending evaluate follow-up to %s", agent_label(alias, state))

        api.followup(
            agent_id=state.agent_ids[alias],
            prompt=evaluate_prompt(others, branch_names=state.branch_names or None),
        )

    # Wait for all SENT agents using persisted message counts
    pending = {
        alias: (state.agent_ids[alias], state.sent_msg_counts.get(alias, 0))
        for alias in state.alias_mapping
        if state.phase_progress.get(alias) == ProgressStatus.SENT
    }
    if pending:
        wait_for_all_followups(api, pending)

    # Extract critiques
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue
        conversation = api.get_conversation(state.agent_ids[alias])
        _update_token_usage(state, alias, conversation)
        state.critiques[alias] = extract_latest_response(conversation)
        state.phase_progress[alias] = ProgressStatus.DONE
        _record_timing_end(state, alias, "evaluate")
        _save()

    state.phase = Phase.REVISE
    state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
    state.sent_msg_counts = {}
    _save()


# ---------------------------------------------------------------------------
# Phase 3: Revise (parallel)
# ---------------------------------------------------------------------------


def step_revise(
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.yaml"
) -> None:
    """Each agent revises its solution based on all three critiques."""
    _save = _saver(state, state_path)

    # Send all follow-ups, persisting message counts for resume safety.
    # On resume, re-send to SENT agents whose message count hasn't changed.
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue

        all_critiques = list(state.critiques.items())
        random.shuffle(all_critiques)

        if state.phase_progress.get(alias) == ProgressStatus.SENT:
            current_count = len(api.get_conversation(state.agent_ids[alias]))
            saved_count = state.sent_msg_counts.get(alias, 0)
            if current_count > saved_count:
                continue  # Agent already received and may have replied
            logger.info("Re-sending revise follow-up to %s (crash recovery)", agent_label(alias, state))
        else:
            state.sent_msg_counts[alias] = len(
                api.get_conversation(state.agent_ids[alias])
            )
            state.phase_progress[alias] = ProgressStatus.SENT
            _record_timing_start(state, alias, "revise")
            _save()  # Persist count BEFORE sending to survive crash
            logger.info("Sending revise follow-up to %s", agent_label(alias, state))

        api.followup(
            agent_id=state.agent_ids[alias],
            prompt=revise_prompt(
                all_critiques, branch_names=state.branch_names or None
            ),
        )

    # Wait for all SENT agents using persisted message counts
    pending = {
        alias: (state.agent_ids[alias], state.sent_msg_counts.get(alias, 0))
        for alias in state.alias_mapping
        if state.phase_progress.get(alias) == ProgressStatus.SENT
    }
    if pending:
        wait_for_all_followups(api, pending)

    # Extract revised solutions (with retry on missing tags)
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue
        conversation = api.get_conversation(state.agent_ids[alias])
        _update_token_usage(state, alias, conversation)
        solution, analysis = _extract_with_retry(
            api, state.agent_ids[alias], conversation
        )
        state.solutions[alias] = solution
        state.analyses[alias] = analysis
        state.phase_progress[alias] = ProgressStatus.DONE
        _record_timing_end(state, alias, "revise")
        _capture_agent_metadata(state, alias, api)
        _save()

    state.phase = Phase.VERIFY
    state.phase_progress = {}
    state.verify_progress = ProgressStatus.PENDING
    state.sent_msg_counts = {}
    _save()


# ---------------------------------------------------------------------------
# Phase 4: Verify
# ---------------------------------------------------------------------------


def step_verify(
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.yaml"
) -> None:
    """A rotating judge evaluates all revised solutions for consensus.

    This phase is fully idempotent: the selected judge and pre-followup
    message count are persisted to state *before* the follow-up is sent,
    so a crash-and-restart will not re-select a judge or send a duplicate
    prompt.
    """
    _save = _saver(state, state_path)

    if state.verify_progress == ProgressStatus.DONE:
        return

    # ── Step 1: Select judge (idempotent — only if not already chosen) ──
    if state.verify_judge is None:
        used = state.judge_history
        available = [a for a in state.alias_mapping if a not in used]
        if not available:
            available = list(state.alias_mapping)
        state.verify_judge = random.choice(available)
        state.judge_history.append(state.verify_judge)
        _save()

    judge = state.verify_judge
    logger.info("Judge for round %d: %s", state.round, agent_label(judge, state))

    # ── Step 2: Send verdict prompt (with crash-recovery re-send) ──
    need_send = False
    if state.verify_progress != ProgressStatus.SENT:
        # Fresh send
        state.verify_prev_msg_count = len(api.get_conversation(state.agent_ids[judge]))
        state.verify_progress = ProgressStatus.SENT
        _save()  # Persist BEFORE the follow-up so a crash won't re-send
        need_send = True
    else:
        # Resume path: re-send if the judge never got the message
        current_count = len(api.get_conversation(state.agent_ids[judge]))
        saved_count = state.verify_prev_msg_count or 0
        if current_count <= saved_count:
            logger.info(
                "Re-sending verify follow-up to judge %s (crash recovery)", agent_label(judge, state)
            )
            need_send = True

    if need_send:
        solutions = list(state.solutions.items())
        analyses = list(state.analyses.items())
        logger.info("Sending verify follow-up to judge %s", agent_label(judge, state))
        api.followup(
            agent_id=state.agent_ids[judge],
            prompt=verify_prompt(
                solutions, analyses, branch_names=state.branch_names or None
            ),
        )

    # ── Step 3: Wait for response and extract verdict ──
    prev_count = state.verify_prev_msg_count or 0
    wait_for_followup(api, state.agent_ids[judge], prev_count)

    conversation = api.get_conversation(state.agent_ids[judge])
    _update_token_usage(state, judge, conversation)
    verdict_text = extract_latest_response(conversation)

    verdict = parse_verdict(verdict_text)

    # If the verdict was extracted via keyword fallback (no <verdict> tag
    # and no convergence_score), re-prompt the judge once for proper
    # formatting.  This improves reliability without changing the outcome
    # when the re-prompt succeeds.
    if verdict.convergence_score is None and extract_xml_section(verdict_text, "verdict") is None:
        logger.warning(
            "Verdict extracted via keyword fallback; re-prompting judge for "
            "structured <verdict> block"
        )
        retry_prev = len(conversation)
        api.followup(agent_id=state.agent_ids[judge], prompt=VERDICT_RETRY_PROMPT)
        wait_for_followup(api, state.agent_ids[judge], retry_prev)
        conversation = api.get_conversation(state.agent_ids[judge])
        _update_token_usage(state, judge, conversation)
        retry_text = extract_latest_response(conversation)
        retry_verdict = parse_verdict(retry_text)
        # Use the retry result if it has a proper XML verdict
        if extract_xml_section(retry_text, "verdict") is not None:
            verdict = retry_verdict
            verdict_text = retry_text
            logger.info("Verdict re-prompt succeeded with structured XML")
        else:
            logger.warning("Verdict re-prompt still lacks <verdict> tag; using original")

    logger.info("Verdict: %s (score=%s)", verdict.decision, verdict.convergence_score)

    # ── Step 4: Enforce convergence_score >= 8 for consensus ──
    if (
        verdict.decision == VerdictDecision.CONSENSUS
        and verdict.convergence_score is not None
        and verdict.convergence_score < 8
    ):
        logger.warning(
            "Judge declared CONSENSUS but convergence_score=%d < 8; "
            "overriding to CONTINUE per proposal rules",
            verdict.convergence_score,
        )
        verdict.decision = VerdictDecision.CONTINUE

    # ── Step 5: Run optional verification commands for code tasks ──
    verify_failed = False
    if state.config.verify_commands and verdict.decision == VerdictDecision.CONSENSUS:
        state.verify_results = []
        for cmd in state.config.verify_commands:
            cmd_prev_count = len(api.get_conversation(state.agent_ids[judge]))
            logger.info("Running verify command via judge: %s", cmd)
            api.followup(
                agent_id=state.agent_ids[judge],
                prompt=f"Run this command and report the result: {cmd}",
            )
            wait_for_followup(api, state.agent_ids[judge], cmd_prev_count)
            cmd_conversation = api.get_conversation(state.agent_ids[judge])
            _update_token_usage(state, judge, cmd_conversation)
            cmd_result = extract_latest_response(cmd_conversation)
            state.verify_results.append(cmd_result)
            _save()
            # Detect failure keywords in result
            lower = cmd_result.lower()
            if any(kw in lower for kw in ("fail", "error", "exception", "exit code")):
                verify_failed = True
                logger.warning("Verify command '%s' appears to have failed", cmd)

        # In gating mode, override consensus when verify commands fail
        if verify_failed and state.config.verify_mode == "gating":
            logger.warning(
                "Verify commands failed in gating mode; overriding CONSENSUS to CONTINUE"
            )
            verdict.decision = VerdictDecision.CONTINUE

    # ── Step 6: Determine next phase ──
    # Always persist the verdict text so post-hoc analysis is possible,
    # even on CONTINUE rounds where the arena loops back.
    state.verdict_history.append(verdict_text)

    if verdict.decision == VerdictDecision.CONSENSUS:
        state.phase = Phase.DONE
        state.completed = True
        state.consensus_reached = True
        state.final_verdict = verdict_text
        state.verify_progress = ProgressStatus.DONE
    elif state.round >= state.config.max_rounds:
        state.phase = Phase.DONE
        state.completed = True
        state.consensus_reached = False
        state.final_verdict = verdict_text
        state.verify_progress = ProgressStatus.DONE
    else:
        # Persist verdict text on CONTINUE so the judge's reasoning is
        # not discarded (arena-run-summary2 issue #2).
        state.final_verdict = verdict_text
        state.round += 1
        state.phase = Phase.EVALUATE
        state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
        state.verify_progress = ProgressStatus.PENDING
        # Clear per-round transient state
        state.critiques = {}
        state.verify_judge = None
        state.verify_prev_msg_count = None
        state.verify_results = []

    _save()
