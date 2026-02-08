"""Tests for the Cursor Cloud Agents API client."""

from arena.api import DEFAULT_TIMEOUT, CursorCloudAPI


class TestCursorCloudAPIInit:
    def test_default_timeout(self) -> None:
        api = CursorCloudAPI("test-key")
        assert api.timeout == DEFAULT_TIMEOUT

    def test_custom_timeout(self) -> None:
        api = CursorCloudAPI("test-key", timeout=120)
        assert api.timeout == 120

    def test_session_auth(self) -> None:
        api = CursorCloudAPI("my-key")
        assert api.session.auth == ("my-key", "")

    def test_session_content_type(self) -> None:
        api = CursorCloudAPI("test-key")
        assert api.session.headers.get("Content-Type") == "application/json"

    def test_repo_url_expansion(self) -> None:
        """launch() should expand shorthand owner/repo to full GitHub URL."""
        from unittest.mock import MagicMock

        api = CursorCloudAPI("test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "agent-1"}
        mock_response.raise_for_status = MagicMock()

        api.session.request = MagicMock(return_value=mock_response)  # type: ignore[assignment]
        api.launch(prompt="test", repo="owner/repo", ref="main")
        call_kwargs = api.session.request.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["source"]["repository"] == "https://github.com/owner/repo"

    def test_full_url_not_expanded(self) -> None:
        """launch() should not modify already-full URLs."""
        from unittest.mock import MagicMock

        api = CursorCloudAPI("test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "agent-1"}
        mock_response.raise_for_status = MagicMock()

        api.session.request = MagicMock(return_value=mock_response)  # type: ignore[assignment]
        api.launch(
            prompt="test",
            repo="https://github.com/custom/repo",
            ref="main",
        )
        call_kwargs = api.session.request.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["source"]["repository"] == "https://github.com/custom/repo"
