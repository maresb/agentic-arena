"""Phase implementations for the arena consensus loop.

Each phase function mutates the :class:`ArenaState` in place and persists it
after every meaningful step. The orchestrator can be killed and restarted
at any point — previously completed work is not re-done.
"""

from __future__ import annotations

import logging
import random

from arena.api import CursorCloudAPI, wait_for_agent, wait_for_all_agents
from arena.extraction import (
    VerdictDecision,
    extract_latest_response,
    extract_solution_and_analysis,
    extract_solution_and_analysis_from_latest,
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


# ---------------------------------------------------------------------------
# Phase 1: Solve (parallel)
# ---------------------------------------------------------------------------


def step_solve(state: ArenaState, api: CursorCloudAPI) -> None:
    """Launch agents to solve the task independently in parallel."""
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
                model=MODELS[model],
            )
            state.agent_ids[alias] = agent["id"]
            save_state(state)

    # Poll all pending agents until finished (truly parallel)
    pending = {
        alias: state.agent_ids[alias]
        for alias in state.alias_mapping
        if state.phase_progress.get(alias) != ProgressStatus.DONE
    }
    if pending:
        wait_for_all_agents(api, pending)

    # Extract content from all finished agents
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue
        conversation = api.get_conversation(state.agent_ids[alias])
        solution, analysis = extract_solution_and_analysis(conversation)
        state.solutions[alias] = solution
        state.analyses[alias] = analysis
        state.phase_progress[alias] = ProgressStatus.DONE
        save_state(state)

    state.phase = Phase.EVALUATE
    state.phase_progress = {
        a: ProgressStatus.PENDING for a in state.alias_mapping
    }
    save_state(state)


# ---------------------------------------------------------------------------
# Phase 2: Evaluate (parallel)
# ---------------------------------------------------------------------------


def step_evaluate(state: ArenaState, api: CursorCloudAPI) -> None:
    """Each agent critiques the other two solutions without revising its own."""
    # Send all follow-ups first (parallel launch)
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) in (
            ProgressStatus.SENT,
            ProgressStatus.DONE,
        ):
            continue

        others = [(k, v) for k, v in state.solutions.items() if k != alias]
        random.shuffle(others)  # Presentation-order neutrality

        logger.info("Sending evaluate follow-up to %s", alias)
        api.followup(
            agent_id=state.agent_ids[alias],
            prompt=evaluate_prompt(others),
        )
        state.phase_progress[alias] = ProgressStatus.SENT
        save_state(state)

    # Poll all agents until finished (truly parallel)
    pending = {
        alias: state.agent_ids[alias]
        for alias in state.alias_mapping
        if state.phase_progress.get(alias) != ProgressStatus.DONE
    }
    if pending:
        wait_for_all_agents(api, pending)

    # Extract critiques
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue
        conversation = api.get_conversation(state.agent_ids[alias])
        state.critiques[alias] = extract_latest_response(conversation)
        state.phase_progress[alias] = ProgressStatus.DONE
        save_state(state)

    state.phase = Phase.REVISE
    state.phase_progress = {
        a: ProgressStatus.PENDING for a in state.alias_mapping
    }
    save_state(state)


# ---------------------------------------------------------------------------
# Phase 3: Revise (parallel)
# ---------------------------------------------------------------------------


def step_revise(state: ArenaState, api: CursorCloudAPI) -> None:
    """Each agent revises its solution based on all three critiques."""
    # Send all follow-ups first
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) in (
            ProgressStatus.SENT,
            ProgressStatus.DONE,
        ):
            continue

        all_critiques = list(state.critiques.items())
        random.shuffle(all_critiques)

        logger.info("Sending revise follow-up to %s", alias)
        api.followup(
            agent_id=state.agent_ids[alias],
            prompt=revise_prompt(all_critiques),
        )
        state.phase_progress[alias] = ProgressStatus.SENT
        save_state(state)

    # Poll all agents until finished
    pending = {
        alias: state.agent_ids[alias]
        for alias in state.alias_mapping
        if state.phase_progress.get(alias) != ProgressStatus.DONE
    }
    if pending:
        wait_for_all_agents(api, pending)

    # Extract revised solutions
    for alias in state.alias_mapping:
        if state.phase_progress.get(alias) == ProgressStatus.DONE:
            continue
        conversation = api.get_conversation(state.agent_ids[alias])
        solution, analysis = extract_solution_and_analysis_from_latest(conversation)
        state.solutions[alias] = solution
        state.analyses[alias] = analysis
        state.phase_progress[alias] = ProgressStatus.DONE
        save_state(state)

    state.phase = Phase.VERIFY
    state.phase_progress = {"verify": ProgressStatus.PENDING}
    save_state(state)


# ---------------------------------------------------------------------------
# Phase 4: Verify
# ---------------------------------------------------------------------------


def step_verify(state: ArenaState, api: CursorCloudAPI) -> None:
    """A rotating judge evaluates all revised solutions for consensus."""
    if state.phase_progress.get("verify") == ProgressStatus.DONE:
        return

    # Select judge — rotate through aliases, randomize within available
    used = state.judge_history
    available = [a for a in state.alias_mapping if a not in used]
    if not available:
        available = list(state.alias_mapping)
    judge = random.choice(available)
    state.judge_history.append(judge)
    logger.info("Selected judge: %s (round %d)", judge, state.round)

    # Collect inputs
    solutions = list(state.solutions.items())
    analyses = list(state.analyses.items())

    logger.info("Sending verify follow-up to judge %s", judge)
    api.followup(
        agent_id=state.agent_ids[judge],
        prompt=verify_prompt(solutions, analyses),
    )
    wait_for_agent(api, state.agent_ids[judge])

    conversation = api.get_conversation(state.agent_ids[judge])
    verdict_text = extract_latest_response(conversation)

    verdict = parse_verdict(verdict_text)
    logger.info(
        "Verdict: %s (score=%s)", verdict.decision, verdict.convergence_score
    )

    # Run optional verification commands for code tasks
    if (
        state.config.verify_commands
        and verdict.decision == VerdictDecision.CONSENSUS
    ):
        for cmd in state.config.verify_commands:
            logger.info("Running verify command via judge: %s", cmd)
            api.followup(
                agent_id=state.agent_ids[judge],
                prompt=f"Run this command and report the result: {cmd}",
            )
            wait_for_agent(api, state.agent_ids[judge])

    # Determine next phase
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
        state.phase_progress = {
            a: ProgressStatus.PENDING for a in state.alias_mapping
        }
        # Clear critiques for the new round
        state.critiques = {}

    state.phase_progress["verify"] = ProgressStatus.DONE
    save_state(state)
