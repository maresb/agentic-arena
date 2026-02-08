"""Tests for the Cursor Cloud Agents API client."""

from arena.api import DEFAULT_TIMEOUT, CursorCloudAPI


class TestCursorCloudAPIInit:
    def test_default_timeout(self) -> None:
        api = CursorCloudAPI("test-key")
        assert api.timeout == DEFAULT_TIMEOUT

    def test_custom_timeout(self) -> None:
        api = CursorCloudAPI("test-key", timeout=120)
        assert api.timeout == 120

    def test_auth_tuple(self) -> None:
        api = CursorCloudAPI("my-key")
        assert api.auth == ("my-key", "")

    def test_repo_url_expansion(self) -> None:
        """launch() should expand shorthand owner/repo to full GitHub URL."""
        from unittest.mock import patch, MagicMock

        api = CursorCloudAPI("test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "agent-1"}
        mock_response.raise_for_status = MagicMock()

        with patch("requests.request", return_value=mock_response) as mock_req:
            api.launch(prompt="test", repo="owner/repo", ref="main")
            call_kwargs = mock_req.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["source"]["repository"] == "https://github.com/owner/repo"

    def test_full_url_not_expanded(self) -> None:
        """launch() should not modify already-full URLs."""
        from unittest.mock import patch, MagicMock

        api = CursorCloudAPI("test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "agent-1"}
        mock_response.raise_for_status = MagicMock()

        with patch("requests.request", return_value=mock_response) as mock_req:
            api.launch(
                prompt="test",
                repo="https://github.com/custom/repo",
                ref="main",
            )
            call_kwargs = mock_req.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["source"]["repository"] == "https://github.com/custom/repo"
