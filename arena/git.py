"""Utilities for fetching files from remote branches via the ``gh`` CLI.

The ``gh`` CLI is used instead of raw HTTP requests to avoid managing a
separate GitHub token -- ``gh`` handles authentication via its own
credential store.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess

logger = logging.getLogger("arena")


def parse_repo_owner_name(repo: str) -> tuple[str, str]:
    """Split a repo identifier into ``(owner, name)``.

    Accepts full HTTPS URLs (``https://github.com/owner/repo``), SSH URLs
    (``git@github.com:owner/repo.git``), and shorthand (``owner/repo``).
    Trailing ``.git`` suffixes are stripped.

    Raises :class:`ValueError` if the input cannot be parsed.
    """
    url = repo.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("https://"):
        # https://github.com/owner/repo
        parts = url.split("/")
        if len(parts) >= 5 and parts[2] in ("github.com", "www.github.com"):
            return parts[3], parts[4]
        raise ValueError(f"Cannot parse GitHub URL: {repo!r}")
    # git@github.com:owner/repo  (SSH)
    if url.startswith("git@"):
        # Strip the "git@<host>:" prefix then split on "/"
        colon_idx = url.index(":")
        path_part = url[colon_idx + 1 :]
        segments = path_part.split("/")
        if len(segments) == 2 and all(segments):
            return segments[0], segments[1]
        raise ValueError(f"Cannot parse SSH URL: {repo!r}")
    # owner/repo
    segments = url.split("/")
    if len(segments) == 2 and all(segments):
        return segments[0], segments[1]
    raise ValueError(
        f"Expected 'owner/repo' or 'https://github.com/owner/repo', got: {repo!r}"
    )


def fetch_file_from_branch(
    repo: str,
    branch: str,
    path: str,
    *,
    timeout: int = 30,
) -> str | None:
    """Fetch a single file's content from a remote branch via ``gh api``.

    Uses the GitHub Contents API:
    ``GET /repos/{owner}/{repo}/contents/{path}?ref={branch}``

    The response payload contains the file content as a base64-encoded
    string under the ``content`` key.

    Returns the decoded text content, or ``None`` if the file does not
    exist or the request fails.

    Parameters
    ----------
    repo:
        Full GitHub URL or ``owner/repo`` shorthand.
    branch:
        Branch name (e.g. ``cursor/my-branch-abc1``).
    path:
        Path to the file within the repository (e.g.
        ``arenas/0003/00-1-solve-agent_a-solution.md``).
    timeout:
        Maximum seconds to wait for the ``gh`` process.
    """
    owner, name = parse_repo_owner_name(repo)
    # gh api returns JSON; we parse it ourselves for the content field.
    api_path = f"/repos/{owner}/{name}/contents/{path}"
    try:
        result = subprocess.run(
            ["gh", "api", "-X", "GET", api_path, "-f", f"ref={branch}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.error("'gh' CLI not found; install it from https://cli.github.com/")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("gh api timed out fetching %s from %s", path, branch)
        return None

    if result.returncode != 0:
        # 404 (file not found) is expected and not worth a warning
        if "Not Found" in result.stderr or "404" in result.stderr:
            logger.debug("File not found on branch: %s @ %s", path, branch)
        else:
            logger.warning(
                "gh api failed (exit %d) for %s @ %s: %s",
                result.returncode,
                path,
                branch,
                result.stderr.strip(),
            )
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse gh api response as JSON for %s @ %s", path, branch
        )
        return None

    content_b64 = data.get("content")
    if not content_b64:
        logger.warning("No 'content' field in response for %s @ %s", path, branch)
        return None

    try:
        return base64.b64decode(content_b64).decode("utf-8")
    except Exception:
        logger.warning("Failed to base64-decode content for %s @ %s", path, branch)
        return None


def default_repo_from_remote(remote: str = "origin") -> str | None:
    """Derive an ``owner/repo`` string from a git remote URL.

    Runs ``git remote get-url <remote>`` and parses the result using
    :func:`parse_repo_owner_name`.  Returns ``None`` if the command
    fails or the URL is not a recognizable GitHub URL.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    if not url:
        return None
    try:
        owner, name = parse_repo_owner_name(url)
        return f"{owner}/{name}"
    except ValueError:
        return None
