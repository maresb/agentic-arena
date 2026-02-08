"""Phase implementations for the arena consensus loop.

Each phase function mutates the :class:`ArenaState` in place and persists it
after every meaningful step. The orchestrator can be killed and restarted
at any point — previously completed work is not re-done.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable

from arena.api import (
    CursorCloudAPI,
    wait_for_all_agents,
    wait_for_all_followups,
    wait_for_followup,
)
from arena.extraction import (
    RETRY_PROMPT,
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
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.json"
) -> None:
    """Launch agents to solve the task independently in parallel."""
    _save = _saver(state, state_path)

    # Launch agents that haven't started yet
    for alias, model in state.alias_mapping.items():
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue
        if alias not in state.agent_ids:
            logger.info("Launching agent %s (model=%s)", alias, model)
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
        _save()

    state.phase = Phase.EVALUATE
    state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
    state.sent_msg_counts = {}
    _save()


# ---------------------------------------------------------------------------
# Phase 2: Evaluate (parallel)
# ---------------------------------------------------------------------------


def step_evaluate(
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.json"
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
            logger.info("Re-sending evaluate follow-up to %s (crash recovery)", alias)
        else:
            state.sent_msg_counts[alias] = len(
                api.get_conversation(state.agent_ids[alias])
            )
            state.phase_progress[alias] = ProgressStatus.SENT
            _save()  # Persist count BEFORE sending to survive crash
            logger.info("Sending evaluate follow-up to %s", alias)

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
        _save()

    state.phase = Phase.REVISE
    state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
    state.sent_msg_counts = {}
    _save()


# ---------------------------------------------------------------------------
# Phase 3: Revise (parallel)
# ---------------------------------------------------------------------------


def step_revise(
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.json"
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
            logger.info("Re-sending revise follow-up to %s (crash recovery)", alias)
        else:
            state.sent_msg_counts[alias] = len(
                api.get_conversation(state.agent_ids[alias])
            )
            state.phase_progress[alias] = ProgressStatus.SENT
            _save()  # Persist count BEFORE sending to survive crash
            logger.info("Sending revise follow-up to %s", alias)

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
    state: ArenaState, api: CursorCloudAPI, *, state_path: str = "arena/state.json"
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
    logger.info("Judge for round %d: %s", state.round, judge)

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
                "Re-sending verify follow-up to judge %s (crash recovery)", judge
            )
            need_send = True

    if need_send:
        solutions = list(state.solutions.items())
        analyses = list(state.analyses.items())
        logger.info("Sending verify follow-up to judge %s", judge)
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
    if verdict.decision == VerdictDecision.CONSENSUS:
        state.phase = Phase.DONE
        state.completed = True
        state.consensus_reached = True
        state.final_verdict = verdict_text
    elif state.round >= state.config.max_rounds:
        state.phase = Phase.DONE
        state.completed = True
        state.consensus_reached = False
        state.final_verdict = verdict_text
    else:
        state.round += 1
        state.phase = Phase.EVALUATE
        state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
        # Clear per-round transient state
        state.critiques = {}
        state.verify_judge = None
        state.verify_prev_msg_count = None
        state.verify_results = []

    state.verify_progress = ProgressStatus.DONE
    _save()
