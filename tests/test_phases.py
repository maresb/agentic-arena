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

    def test_captures_branch_names_from_status(self) -> None:
        """After solve, branch names are extracted from status() responses."""
        state = init_state(task="test", repo="r")
        api = make_mock_api()

        # Make launch return unique IDs
        agent_ids = {}
        call_count = {"n": 0}

        def mock_launch(**kw):
            call_count["n"] += 1
            return {"id": f"id-{call_count['n']}"}

        api.launch.side_effect = mock_launch

        # Status returns branch name in target.branchName
        def mock_status(agent_id):
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
            conversation_response=[{"role": "assistant", "content": "my critique"}]
        )

        step_evaluate(state, api)

        assert state.phase == Phase.REVISE
        for alias in state.alias_mapping:
            assert state.phase_progress[alias] == ProgressStatus.PENDING

    def test_persists_sent_msg_counts(self) -> None:
        """Message counts are persisted in state for resume safety."""
        state = self._make_solved_state()
        api = make_mock_api(
            conversation_response=[{"role": "assistant", "content": "critique text"}]
        )

        step_evaluate(state, api)

        # After completion, sent_msg_counts should be cleared at transition
        assert state.sent_msg_counts == {}

    def test_resumes_with_sent_state(self) -> None:
        """Agents marked SENT from a previous run are waited on, not re-sent."""
        state = self._make_solved_state()
        first_alias = list(state.alias_mapping.keys())[0]
        # Simulate: one agent was already sent in a previous run
        state.phase_progress[first_alias] = ProgressStatus.SENT
        state.sent_msg_counts[first_alias] = 0  # had 0 msgs before send

        api = make_mock_api(
            conversation_response=[{"role": "assistant", "content": "critique text"}]
        )

        step_evaluate(state, api)

        # Should still complete — all three agents get critiques
        assert state.phase == Phase.REVISE
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
        assert state.verify_progress == ProgressStatus.PENDING


class TestStepVerify:
    def _make_revised_state(self) -> ArenaState:
        """Create a state that's ready for verify."""
        state = init_state(task="test", repo="r")
        state.phase = Phase.VERIFY
        state.verify_progress = ProgressStatus.PENDING
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
                    "<verdict>\ndecision: CONTINUE\nconvergence_score: 6\n</verdict>"
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
                    "<verdict>\ndecision: CONTINUE\nconvergence_score: 5\n</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert len(state.judge_history) == 1
        judge = state.judge_history[0]
        assert judge in state.alias_mapping

    def test_verify_idempotent_judge_selection(self) -> None:
        """If verify_judge is already set, step_verify uses it (no re-selection)."""
        state = self._make_revised_state()
        # Pre-select a specific judge
        state.verify_judge = "agent_a"
        state.judge_history = ["agent_a"]
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\ndecision: CONSENSUS\nconvergence_score: 9\n</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        # Should still have only one entry — no duplicate append
        assert state.judge_history == ["agent_a"]
        assert state.completed is True

    def test_verify_idempotent_sent_state(self) -> None:
        """If verify is already SENT, step_verify skips sending the follow-up."""
        state = self._make_revised_state()
        state.verify_judge = "agent_a"
        state.judge_history = ["agent_a"]
        state.verify_progress = ProgressStatus.SENT
        # prev_msg_count=0 means the conversation already has a response
        # (the agent responded to the follow-up sent in a previous run)
        state.verify_prev_msg_count = 0
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\ndecision: CONSENSUS\nconvergence_score: 9\n</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        # Follow-up should NOT have been called (already sent)
        api.followup.assert_not_called()
        assert state.completed is True

    def test_consensus_overridden_when_score_below_8(self) -> None:
        """Judge says CONSENSUS but score < 8 => override to CONTINUE."""
        state = self._make_revised_state()
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\n"
                    "decision: CONSENSUS\n"
                    "convergence_score: 6\n"
                    "remaining_disagreements: 2\n"
                    "</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        # Should NOT be consensus — score < 8
        assert state.completed is False
        assert state.phase == Phase.EVALUATE
        assert state.round == 1

    def test_consensus_accepted_when_score_is_8(self) -> None:
        """Score == 8 is the threshold — should accept consensus."""
        state = self._make_revised_state()
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\ndecision: CONSENSUS\nconvergence_score: 8\n</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert state.completed is True
        assert state.consensus_reached is True

    def test_verify_clears_transient_state_on_continue(self) -> None:
        """On CONTINUE, verify_judge/verify_prev_msg_count are cleared."""
        state = self._make_revised_state()
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\ndecision: CONTINUE\nconvergence_score: 4\n</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert state.verify_judge is None
        assert state.verify_prev_msg_count is None
        assert state.verify_results == []

    def test_verdict_text_persisted_on_continue(self) -> None:
        """On CONTINUE, final_verdict is set so the judge's reasoning is preserved."""
        state = self._make_revised_state()
        verdict_content = (
            "My analysis...\n"
            "<verdict>\ndecision: CONTINUE\nconvergence_score: 5\n</verdict>"
        )
        verdict_response = [
            {"role": "assistant", "content": verdict_content}
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert state.final_verdict is not None
        assert "CONTINUE" in state.final_verdict

    def test_verdict_history_accumulates(self) -> None:
        """Each verify round appends to verdict_history."""
        state = self._make_revised_state()
        verdict_content = (
            "<verdict>\ndecision: CONTINUE\nconvergence_score: 5\n</verdict>"
        )
        verdict_response = [
            {"role": "assistant", "content": verdict_content}
        ]
        api = make_mock_api(conversation_response=verdict_response)

        assert state.verdict_history == []
        step_verify(state, api)
        assert len(state.verdict_history) == 1
        assert "CONTINUE" in state.verdict_history[0]

    def test_verdict_history_on_consensus(self) -> None:
        """Consensus verdict is also appended to verdict_history."""
        state = self._make_revised_state()
        verdict_response = [
            {
                "role": "assistant",
                "content": (
                    "<verdict>\ndecision: CONSENSUS\nconvergence_score: 9\n</verdict>"
                ),
            }
        ]
        api = make_mock_api(conversation_response=verdict_response)

        step_verify(state, api)

        assert len(state.verdict_history) == 1
        assert "CONSENSUS" in state.verdict_history[0]
        assert state.final_verdict is not None


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
