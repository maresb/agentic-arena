"""Tests for arena.git — GitHub file fetching via ``gh`` CLI."""

from __future__ import annotations

import base64
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from arena.git import fetch_file_from_branch, parse_repo_owner_name


# ---------------------------------------------------------------------------
# parse_repo_owner_name
# ---------------------------------------------------------------------------


class TestParseRepoOwnerName:
    def test_shorthand(self) -> None:
        assert parse_repo_owner_name("owner/repo") == ("owner", "repo")

    def test_https_url(self) -> None:
        assert parse_repo_owner_name("https://github.com/owner/repo") == (
            "owner",
            "repo",
        )

    def test_https_url_trailing_slash(self) -> None:
        assert parse_repo_owner_name("https://github.com/owner/repo/") == (
            "owner",
            "repo",
        )

    def test_https_url_dot_git(self) -> None:
        assert parse_repo_owner_name("https://github.com/owner/repo.git") == (
            "owner",
            "repo",
        )

    def test_www_github(self) -> None:
        assert parse_repo_owner_name("https://www.github.com/owner/repo") == (
            "owner",
            "repo",
        )

    def test_invalid_single_segment(self) -> None:
        with pytest.raises(ValueError, match="Expected"):
            parse_repo_owner_name("just-a-name")

    def test_invalid_empty_segments(self) -> None:
        with pytest.raises(ValueError, match="Expected"):
            parse_repo_owner_name("/repo")

    def test_invalid_url_not_github(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_repo_owner_name("https://gitlab.com/owner/repo")


# ---------------------------------------------------------------------------
# fetch_file_from_branch
# ---------------------------------------------------------------------------


def _make_gh_response(content: str) -> subprocess.CompletedProcess[str]:
    """Build a mock ``gh api`` response with base64-encoded content."""
    encoded = base64.b64encode(content.encode()).decode()
    payload = json.dumps({"content": encoded, "encoding": "base64"})
    return subprocess.CompletedProcess(
        args=["gh", "api", "..."],
        returncode=0,
        stdout=payload,
        stderr="",
    )


def _make_gh_error(
    returncode: int = 1, stderr: str = "Not Found"
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh", "api", "..."],
        returncode=returncode,
        stdout="",
        stderr=stderr,
    )


class TestFetchFileFromBranch:
    @patch("arena.git.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_gh_response("# My Solution\nHello world")
        result = fetch_file_from_branch(
            "owner/repo",
            "cursor/my-branch",
            "arenas/0001/00-1-solve-agent_a-solution.md",
        )
        assert result == "# My Solution\nHello world"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "gh" in args[0]
        assert (
            "/repos/owner/repo/contents/arenas/0001/00-1-solve-agent_a-solution.md"
            in args
        )

    @patch("arena.git.subprocess.run")
    def test_full_url_repo(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_gh_response("content")
        result = fetch_file_from_branch(
            "https://github.com/owner/repo", "branch", "file.md"
        )
        assert result == "content"
        args = mock_run.call_args[0][0]
        assert "/repos/owner/repo/contents/file.md" in args

    @patch("arena.git.subprocess.run")
    def test_file_not_found(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_gh_error(1, "Not Found")
        result = fetch_file_from_branch("owner/repo", "branch", "missing.md")
        assert result is None

    @patch("arena.git.subprocess.run")
    def test_gh_not_installed(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("No such file: 'gh'")
        result = fetch_file_from_branch("owner/repo", "branch", "file.md")
        assert result is None

    @patch("arena.git.subprocess.run")
    def test_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=30)
        result = fetch_file_from_branch("owner/repo", "branch", "file.md")
        assert result is None

    @patch("arena.git.subprocess.run")
    def test_invalid_json_response(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="not json", stderr=""
        )
        result = fetch_file_from_branch("owner/repo", "branch", "file.md")
        assert result is None

    @patch("arena.git.subprocess.run")
    def test_missing_content_field(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout='{"name": "file.md"}', stderr=""
        )
        result = fetch_file_from_branch("owner/repo", "branch", "file.md")
        assert result is None

    @patch("arena.git.subprocess.run")
    def test_non_404_error(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_gh_error(1, "rate limit exceeded")
        result = fetch_file_from_branch("owner/repo", "branch", "file.md")
        assert result is None

    @patch("arena.git.subprocess.run")
    def test_unicode_content(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _make_gh_response("Caf\u00e9 \u2603 snowman")
        result = fetch_file_from_branch("owner/repo", "branch", "file.md")
        assert result == "Caf\u00e9 \u2603 snowman"
