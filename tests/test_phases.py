"""Tests for the phase logic using a mock API.

These tests verify the orchestrator's control flow and state transitions
without making real API calls.
"""

import json

from unittest.mock import MagicMock, patch

from arena.phases import (
    step_evaluate,
    step_revise,
    step_solve,
)
from arena.state import ArenaState, Phase, ProgressStatus, init_state


def make_mock_api(
    conversation_response: list[dict] | None = None,
    launch_id: str = "agent-123",
    *,
    status_extra: dict | None = None,
) -> MagicMock:
    """Create a mock CursorCloudAPI with sensible defaults.

    The mock simulates conversation growth: each follow-up appends a
    user + assistant message pair so that ``wait_for_followup`` sees
    ``len(messages) > previous_msg_count`` and completes.
    """
    api = MagicMock()
    api.launch.return_value = {"id": launch_id}
    base_status: dict = {"status": "FINISHED"}
    if status_extra:
        base_status.update(status_extra)
    api.status.return_value = base_status

    if conversation_response is None:
        conversation_response = [
            {"role": "assistant", "content": "Default assistant response"},
        ]

    # Track follow-ups per agent to simulate conversation growth
    followup_counts: dict[str, int] = {}

    def mock_followup(agent_id: str, prompt: str) -> dict:
        followup_counts[agent_id] = followup_counts.get(agent_id, 0) + 1
        return {"id": agent_id}

    def mock_get_conversation(agent_id: str) -> list[dict]:
        n = followup_counts.get(agent_id, 0)
        base = list(conversation_response)
        for _ in range(n):
            base.append({"role": "user", "content": "follow-up"})
            base.append(dict(conversation_response[-1]))
        return base

    api.followup.side_effect = mock_followup
    api.get_conversation.side_effect = mock_get_conversation
    return api


def _make_vote_response(score: int = 9, best: list[str] | None = None) -> list[dict]:
    """Build a mock conversation where the latest message is a vote verdict JSON."""
    best = best or ["agent_a"]
    divergences = (
        []
        if score >= 10
        else [{"topic": "test issue", "description": "still disagree"}]
    )
    verdict = {
        "convergence_score": score,
        "best_solutions": best,
        "divergences": divergences,
        "rationale": "Test rationale",
    }
    return [
        {
            "role": "assistant",
            "content": json.dumps(verdict),
        }
    ]


def _make_vote_json(score: int = 9, best: list[str] | None = None) -> str:
    """Build verdict JSON string for mocking committed verdict files."""
    best = best or ["agent_a"]
    divergences = (
        []
        if score >= 10
        else [{"topic": "test issue", "description": "still disagree"}]
    )
    return json.dumps(
        {
            "convergence_score": score,
            "best_solutions": best,
            "divergences": divergences,
            "rationale": "Test rationale",
        }
    )


def _branch_file_mock(
    *,
    solution: str = "Mock solution content",
    analysis: str = "Mock analysis content",
    critique: str = "Mock critique content",
    verdict_json: str | None = None,
) -> MagicMock:
    """Return a mock for ``fetch_file_from_branch`` that returns content by file suffix."""
    if verdict_json is None:
        verdict_json = _make_vote_json()

    def _fetch(repo: str, branch: str, path: str, **kw: object) -> str | None:
        if path.endswith("-solution.md"):
            return solution
        if path.endswith("-analysis.md"):
            return analysis
        if path.endswith("-critique.md"):
            return critique
        if path.endswith("-verdict.json"):
            return verdict_json
        return None

    return MagicMock(side_effect=_fetch)


def _add_branch_names(state: ArenaState) -> None:
    """Set dummy branch names so _fetch_with_retry can proceed."""
    for alias in state.alias_mapping:
        state.branch_names[alias] = f"cursor/branch-{alias}"


class TestStepSolve:
    @patch("arena.phases.fetch_file_from_branch")
    def test_launches_three_agents(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = _branch_file_mock().side_effect
        state = init_state(task="test task", repo="owner/repo")
        api = make_mock_api()

        # Make launch return different IDs
        ids = iter(["id-1", "id-2", "id-3"])
        api.launch.side_effect = lambda **kw: {"id": next(ids)}

        step_solve(state, api)

        assert api.launch.call_count == 3
        assert len(state.agent_ids) == 3
        assert state.phase == Phase.EVALUATE
        for alias in state.alias_mapping:
            assert alias in state.solutions
            assert alias in state.analyses

    @patch("arena.phases.fetch_file_from_branch", return_value=None)
    def test_skips_already_done_agents(self, _mock_fetch: MagicMock) -> None:
        state = init_state(task="test", repo="r")
        # Mark one agent as done
        first_alias = list(state.alias_mapping.keys())[0]
        state.phase_progress[first_alias] = ProgressStatus.DONE
        state.agent_ids[first_alias] = "existing-id"
        state.solutions[first_alias] = "existing solution"
        state.analyses[first_alias] = "existing analysis"

        api = make_mock_api()
        ids = iter(["id-1", "id-2"])
        api.launch.side_effect = lambda **kw: {"id": next(ids)}

        step_solve(state, api)

        # Should only launch 2 agents
        assert api.launch.call_count == 2

    @patch("arena.phases.fetch_file_from_branch", return_value=None)
    def test_transitions_to_evaluate_phase(self, _mock_fetch: MagicMock) -> None:
        state = init_state(task="test", repo="r")
        api = make_mock_api()
        ids = iter(["id-1", "id-2", "id-3"])
        api.launch.side_effect = lambda **kw: {"id": next(ids)}

        step_solve(state, api)

        assert state.phase == Phase.EVALUATE
        for alias in state.alias_mapping:
            assert state.phase_progress[alias] == ProgressStatus.PENDING

    @patch("arena.phases.fetch_file_from_branch", return_value=None)
    def test_captures_branch_names_from_status(self, _mock_fetch: MagicMock) -> None:
        """After solve, branch names are extracted from status() responses."""
        state = init_state(task="test", repo="owner/repo")
        ids = iter(["id-1", "id-2", "id-3"])
        api = make_mock_api()
        api.launch.side_effect = lambda **kw: {"id": next(ids)}

        def mock_status(agent_id: str) -> dict:
            return {
                "status": "FINISHED",
                "target": {"branchName": f"cursor/branch-{agent_id}"},
            }

        api.status.side_effect = mock_status

        step_solve(state, api)

        # All agents should have branch names captured
        assert len(state.branch_names) == 3
        for alias in state.alias_mapping:
            assert alias in state.branch_names
            assert state.branch_names[alias].startswith("cursor/branch-")


class TestStepEvaluate:
    def _make_solved_state(self) -> ArenaState:
        """Create a state that's ready for evaluate."""
        state = init_state(task="test", repo="r")
        state.phase = Phase.EVALUATE
        state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
        for i, alias in enumerate(state.alias_mapping):
            state.agent_ids[alias] = f"agent-{i}"
            state.solutions[alias] = f"Solution from {alias}"
            state.analyses[alias] = f"Analysis from {alias}"
        _add_branch_names(state)
        return state

    @patch("arena.phases.fetch_file_from_branch")
    def test_sends_followups_to_all_agents(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = _branch_file_mock(
            verdict_json=_make_vote_json(score=5)
        ).side_effect
        state = self._make_solved_state()
        api = make_mock_api()

        step_evaluate(state, api)

        assert api.followup.call_count == 3
        for alias in state.alias_mapping:
            assert alias in state.critiques

    @patch("arena.phases.fetch_file_from_branch")
    def test_low_score_transitions_to_revise(self, mock_fetch: MagicMock) -> None:
        """Score < 8 means no consensus -> transitions to REVISE."""
        mock_fetch.side_effect = _branch_file_mock(
            verdict_json=_make_vote_json(score=5)
        ).side_effect
        state = self._make_solved_state()
        api = make_mock_api()

        step_evaluate(state, api)

        assert state.phase == Phase.REVISE
        for alias in state.alias_mapping:
            assert state.phase_progress[alias] == ProgressStatus.PENDING

    @patch("arena.phases.fetch_file_from_branch")
    def test_high_score_unanimous_reaches_consensus(
        self, mock_fetch: MagicMock
    ) -> None:
        """Score >= 8 and unanimous vote -> consensus -> DONE."""
        state = self._make_solved_state()
        aliases = list(state.alias_mapping.keys())
        winner = aliases[0]

        mock_fetch.side_effect = _branch_file_mock(
            verdict_json=_make_vote_json(score=9, best=[winner])
        ).side_effect
        api = make_mock_api()

        step_evaluate(state, api)

        assert state.phase == Phase.DONE
        assert state.completed is True
        assert state.consensus_reached is True
        assert state.verify_winner == winner

    @patch("arena.phases.fetch_file_from_branch")
    def test_strips_self_votes(self, mock_fetch: MagicMock) -> None:
        """If an agent votes for itself, the self-vote is silently stripped."""
        state = self._make_solved_state()
        aliases = list(state.alias_mapping.keys())

        mock_fetch.side_effect = _branch_file_mock(
            verdict_json=_make_vote_json(score=5, best=[aliases[0], aliases[1]])
        ).side_effect
        api = make_mock_api()

        step_evaluate(state, api)

        # aliases[0]'s self-vote should be stripped from their own entry
        assert aliases[0] not in state.verify_votes.get(aliases[0], [])
        # aliases[1]'s self-vote should be stripped from their own entry
        assert aliases[1] not in state.verify_votes.get(aliases[1], [])

    @patch("arena.phases.fetch_file_from_branch")
    def test_persists_sent_msg_counts(self, mock_fetch: MagicMock) -> None:
        """Message counts are persisted in state for resume safety."""
        mock_fetch.side_effect = _branch_file_mock(
            verdict_json=_make_vote_json(score=5)
        ).side_effect
        state = self._make_solved_state()
        api = make_mock_api()

        step_evaluate(state, api)

        # After completion, sent_msg_counts should be cleared at transition
        assert state.sent_msg_counts == {}

    @patch("arena.phases.fetch_file_from_branch")
    def test_verdict_history_accumulated(self, mock_fetch: MagicMock) -> None:
        """Each evaluate round appends to verdict_history."""
        mock_fetch.side_effect = _branch_file_mock(
            verdict_json=_make_vote_json(score=5)
        ).side_effect
        state = self._make_solved_state()
        api = make_mock_api()
        assert state.verdict_history == []

        step_evaluate(state, api)

        assert len(state.verdict_history) == 1

    @patch("arena.phases.fetch_file_from_branch")
    def test_max_rounds_completes_without_consensus(
        self, mock_fetch: MagicMock
    ) -> None:
        """When round >= max_rounds, arena completes even without consensus."""
        mock_fetch.side_effect = _branch_file_mock(
            verdict_json=_make_vote_json(score=5)
        ).side_effect
        state = self._make_solved_state()
        state.round = 3  # max_rounds defaults to 3
        api = make_mock_api()

        step_evaluate(state, api)

        assert state.phase == Phase.DONE
        assert state.completed is True
        assert state.consensus_reached is False

    @patch("arena.phases.fetch_file_from_branch")
    def test_resumes_with_sent_state(self, mock_fetch: MagicMock) -> None:
        """Agents marked SENT from a previous run are waited on, not re-sent."""
        mock_fetch.side_effect = _branch_file_mock(
            verdict_json=_make_vote_json(score=5)
        ).side_effect
        state = self._make_solved_state()
        first_alias = list(state.alias_mapping.keys())[0]
        # Simulate: one agent was already sent in a previous run
        state.phase_progress[first_alias] = ProgressStatus.SENT
        state.sent_msg_counts[first_alias] = 0  # had 0 msgs before send

        api = make_mock_api()

        step_evaluate(state, api)

        # Should still complete — all three agents done
        assert state.phase in (Phase.REVISE, Phase.DONE)
        for alias in state.alias_mapping:
            assert alias in state.critiques


class TestStepRevise:
    def _make_evaluated_state(self) -> ArenaState:
        """Create a state that's ready for revise."""
        state = init_state(task="test", repo="r")
        state.phase = Phase.REVISE
        state.phase_progress = {a: ProgressStatus.PENDING for a in state.alias_mapping}
        for i, alias in enumerate(state.alias_mapping):
            state.agent_ids[alias] = f"agent-{i}"
            state.solutions[alias] = f"Solution from {alias}"
            state.analyses[alias] = f"Analysis from {alias}"
            state.critiques[alias] = f"Critique from {alias}"
        _add_branch_names(state)
        return state

    @patch("arena.phases.fetch_file_from_branch")
    def test_sends_followups_and_updates_solutions(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = _branch_file_mock().side_effect
        state = self._make_evaluated_state()
        api = make_mock_api()

        step_revise(state, api)

        assert api.followup.call_count == 3
        assert state.phase == Phase.EVALUATE
        for alias in state.alias_mapping:
            assert alias in state.solutions

    @patch("arena.phases.fetch_file_from_branch")
    def test_transitions_to_evaluate_and_increments_round(
        self, mock_fetch: MagicMock
    ) -> None:
        mock_fetch.side_effect = _branch_file_mock().side_effect
        state = self._make_evaluated_state()
        assert state.round == 0
        api = make_mock_api()

        step_revise(state, api)

        assert state.phase == Phase.EVALUATE
        assert state.round == 1
        for alias in state.alias_mapping:
            assert state.phase_progress[alias] == ProgressStatus.PENDING

    @patch("arena.phases.fetch_file_from_branch")
    def test_clears_transient_state(self, mock_fetch: MagicMock) -> None:
        """On transition, per-round state is cleared."""
        mock_fetch.side_effect = _branch_file_mock().side_effect
        state = self._make_evaluated_state()
        state.verify_votes = {"agent_a": ["agent_b"]}
        state.verify_scores = {"agent_a": 5}
        state.verify_divergences = {"agent_a": [{"topic": "x", "description": "y"}]}
        api = make_mock_api()

        step_revise(state, api)

        assert state.critiques == {}
        assert state.verify_votes == {}
        assert state.verify_scores == {}
        assert state.verify_divergences == {}
        assert state.verify_winner is None
