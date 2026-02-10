"""Integration test harness for live API testing.

These tests require a real CURSOR_API_KEY and hit the actual Cursor Cloud
Agents API.  They are skipped by default unless the ``CURSOR_API_KEY``
environment variable is set.

Usage:
    CURSOR_API_KEY=... pixi run pytest tests/test_integration.py -v
"""

from __future__ import annotations

import os

import pytest

# Skip entire module unless we have a real API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("CURSOR_API_KEY"),
    reason="CURSOR_API_KEY not set; skipping integration tests",
)


@pytest.fixture
def api():
    """Create a live CursorCloudAPI client."""
    from arena.api import CursorCloudAPI

    return CursorCloudAPI(os.environ["CURSOR_API_KEY"])


class TestLiveAPI:
    def test_me_endpoint(self, api) -> None:
        """Verify authentication works."""
        result = api.me()
        assert "userEmail" in result or "email" in result or "id" in result

    def test_list_models(self, api) -> None:
        """Verify model listing works."""
        models = api.list_models()
        assert isinstance(models, list)
        assert len(models) > 0

    def test_list_repositories(self, api) -> None:
        """Verify repository listing works."""
        repos = api.list_repositories()
        assert isinstance(repos, list)

    def test_launch_and_stop_agent(self, api) -> None:
        """Launch an agent, verify it starts, then stop it."""
        agent = api.launch(
            prompt="Say hello in one word.",
            repo="maresb/cursor-agentic-arena",
            ref="main",
        )
        agent_id = agent["id"]
        assert agent_id

        info = api.status(agent_id)
        assert info["status"] in ("CREATING", "RUNNING", "FINISHED")

        # Clean up
        api.stop(agent_id)
