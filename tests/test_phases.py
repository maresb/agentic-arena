"""Tests for the phase logic using a mock API.

These tests verify the orchestrator's control flow and state transitions
without making real API calls.
"""

from unittest.mock import MagicMock

from arena.phases import (
    _extract_with_retry,
    step_evaluate,
    step_revise,
    step_solve,
    step_verify,
)
from arena.state import ArenaState, Phase, ProgressStatus, init_state


def make_mock_api(
    conversation_response: list[dict] | None = None,
    launch_id: str = "agent-123",
) -> MagicMock:
    """Create a mock CursorCloudAPI with sensible defaults.

    The mock simulates conversation growth: each follow-up appends a
    user + assistant message pair so that ``wait_for_followup`` sees
    ``len(messages) > previous_msg_count`` and completes.
    """
    api = MagicMock()
    api.launch.return_value = {"id": launch_id}
    api.status.return_value = {"status": "FINISHED"}

    if conversation_response is None:
        conversation_response = [
            {
                "role": "assistant",
                "content": (
                    "<solution>\n## PLAN\nStep 1: Do the thing\n"
                    "## CHANGES\nChanged file.py\n</solution>\n"
                    "<analysis>\n## RISKS\nNone significant\n"
                    "## OPEN QUESTIONS\nNone\n</analysis>"
                ),
            }
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


class TestStepSolve:
    def test_launches_three_agents(self) -> None:
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

    def test_skips_already_done_agents(self) -> None:
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

    def test_transitions_to_evaluate_phase(self) -> None:
        state = init_state(task="test", repo="r")
        api = make_mock_api()
        ids = iter(["id-1", "id-2", "id-3"])
        api.launch.side_effect = lambda **kw: {"id": next(ids)}

        step_solve(state, api)

        assert state.phase == Phase.EVALUATE
        for alias in state.alias_mapping:
            assert state.phase_progress[alias] == ProgressStatus.PENDING


class TestStepEvaluate:
    def _make_solved_state(self) -> ArenaState:
        """Create a state that's ready for evaluate."""
        state = init_state(task="test", repo="r")
        state.phase = Phase.EVALUATE
        state.phase_progress = {
            a: ProgressStatus.PENDING for a in state.alias_mapping
        }
        for i, alias in enumerate(state.alias_mapping):
            state.agent_ids[alias] = f"agent-{i}"
            state.solutions[alias] = f"Solution from {alias}"
            state.analyses[alias] = f"Analysis from {alias}"
        return state

    def test_sends_followups_to_all_agents(self) -> None:
        state = self._make_solved_state()
        api = make_mock_api(
            conversation_response=[
                {"role": "assistant", "content": "critique text here"}
            ]
        )

        step_evaluate(state, api)

        assert api.followup.call_count == 3
        assert state.phase == Phase.REVISE
        for alias in state.alias_mapping:
            assert alias in state.critiques

    def test_transitions_to_revise_phase(self) -> None:
        state = self._make_solved_state()
        api = make_mock_api(
            conversation_response=[
                {"role": "assistant", "content": "my critique"}
            ]
        )

        step_evaluate(state, api)

        assert state.phase == Phase.REVISE
        for alias in state.alias_mapping:
            assert state.phase_progress[alias] == ProgressStatus.PENDING


class TestStepRevise:
    def _make_evaluated_state(self) -> ArenaState:
        """Create a state that's ready for revise."""
        state = init_state(task="test", repo="r")
        state.phase = Phase.REVISE
        state.phase_progress = {
            a: ProgressStatus.PENDING for a in state.alias_mapping
        }
        for i, alias in enumerate(state.alias_mapping):
            state.agent_ids[alias] = f"agent-{i}"
            state.solutions[alias] = f"Solution from {alias}"
            state.analyses[alias] = f"Analysis from {alias}"
            state.critiques[alias] = f"Critique from {alias}"
        return state

    def test_sends_followups_and_updates_solutions(self) -> None:
        state = self._make_evaluated_state()
        api = make_mock_api()  # Default returns XML-tagged response

        step_revise(state, api)

        assert api.followup.call_count == 3
        assert state.phase == Phase.VERIFY
        for alias in state.alias_mapping:
            assert alias in state.solutions

    def test_transitions_to_verify_phase(self) -> None:
        state = self._make_evaluated_state()
        api = make_mock_api()

        step_revise(state, api)

        assert state.phase == Phase.VERIFY
        assert state.phase_progress["verify"] == ProgressStatus.PENDING


class TestStepVerify:
    def _make_revised_state(self) -> ArenaState:
        """Create a state that's ready for verify."""
        state = init_state(task="test", repo="r")
        state.phase = Phase.VERIFY
        state.phase_progress = {"verify": ProgressStatus.PENDING}
        for i, alias in enumerate(state.alias_mapping):
            state.agent_ids[alias] = f"agent-{i}"
            state.solutions[alias] = f"Revised solution from {alias}"
            state.analyses[alias] = f"Revised analysis from {alias}"
            state.critiques[alias] = f"Critique from {alias}"
        return state

    def test_consensus_completes_arena(self) -> None:
        state = self._make_revised_state()
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "Analysis...\n"
                    "<verdict>\n"
                    "decision: CONSENSUS\n"
                    "convergence_score: 9\n"
                    "remaining_disagreements: 0\n"
                    "base_solution: agent_a\n"
                    "modifications: none\n"
                    "</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert state.completed is True
        assert state.consensus_reached is True
        assert state.phase == Phase.DONE
        assert state.final_verdict is not None
        assert len(state.judge_history) == 1

    def test_continue_goes_to_next_round(self) -> None:
        state = self._make_revised_state()
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\n"
                    "decision: CONTINUE\n"
                    "convergence_score: 5\n"
                    "remaining_disagreements: 3\n"
                    "base_solution: merged\n"
                    "modifications: TBD\n"
                    "</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert state.completed is False
        assert state.phase == Phase.EVALUATE
        assert state.round == 1

    def test_max_rounds_reached_completes(self) -> None:
        state = self._make_revised_state()
        state.round = 3
        # config is frozen, so recreate with max_rounds=3
        # (init_state already defaults to 3)
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\n"
                    "decision: CONTINUE\n"
                    "convergence_score: 6\n"
                    "</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert state.completed is True
        assert state.consensus_reached is False
        assert state.phase == Phase.DONE

    def test_judge_rotation(self) -> None:
        state = self._make_revised_state()
        state.judge_history = []
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\n"
                    "decision: CONTINUE\n"
                    "convergence_score: 5\n"
                    "</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert len(state.judge_history) == 1
        judge = state.judge_history[0]
        assert judge in state.alias_mapping


class TestExtractWithRetry:
    def test_no_retry_when_tags_present(self) -> None:
        """If XML tags are present, no follow-up is sent."""
        api = make_mock_api()
        conversation = [
            {
                "role": "assistant",
                "content": (
                    "<solution>\n## PLAN\nStep 1\n</solution>\n"
                    "<analysis>\n## RISKS\nNone\n</analysis>"
                ),
            }
        ]
        solution, analysis = _extract_with_retry(api, "agent-1", conversation)
        assert "## PLAN" in solution
        assert "## RISKS" in analysis
        # No follow-up should have been sent
        api.followup.assert_not_called()

    def test_retry_when_tags_missing(self) -> None:
        """If XML tags are missing, sends RETRY_PROMPT and tries again."""
        api = MagicMock()
        api.status.return_value = {"status": "FINISHED"}

        # First call returns no tags; second returns properly tagged
        call_count = {"n": 0}

        def mock_get_conversation(agent_id: str) -> list[dict]:
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return [{"role": "assistant", "content": "plain text, no tags"}]
            return [
                {"role": "assistant", "content": "plain text, no tags"},
                {"role": "user", "content": "retry prompt"},
                {
                    "role": "assistant",
                    "content": (
                        "<solution>\nRetried plan\n</solution>\n"
                        "<analysis>\nRetried analysis\n</analysis>"
                    ),
                },
            ]

        api.get_conversation.side_effect = mock_get_conversation
        api.followup.return_value = {"id": "agent-1"}

        conversation = [{"role": "assistant", "content": "plain text, no tags"}]
        solution, analysis = _extract_with_retry(api, "agent-1", conversation)

        api.followup.assert_called_once()
        assert "Retried plan" in solution
        assert "Retried analysis" in analysis
