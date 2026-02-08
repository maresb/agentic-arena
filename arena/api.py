"""Cursor Cloud Agents API wrapper with retry and exponential backoff."""

from __future__ import annotations

import logging
import random
import sys
import time
from typing import Any

import requests

# TODO: if more shared utilities emerge beyond is_assistant_message,
# extract them into arena/utils.py to avoid coupling api -> extraction.
from arena.extraction import is_assistant_message

logger = logging.getLogger("arena")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
BASE_BACKOFF = 2.0  # seconds
DEFAULT_TIMEOUT = 60  # seconds per HTTP request


def _emit_poll_dot() -> None:
    """Print a single '.' to stderr as a polling heartbeat.

    Suppressed when the arena logger is at DEBUG level (--verbose mode)
    since full debug lines already provide visibility.
    """
    if logger.getEffectiveLevel() > logging.DEBUG:
        sys.stderr.write(".")
        sys.stderr.flush()


class CursorCloudAPI:
    """HTTP client for the Cursor Cloud Agents API.

    Authentication uses HTTP Basic Auth with the API key as the username
    and an empty password, per the official docs:
    https://cursor.com/docs/api#basic-authentication
    """

    BASE = "https://api.cursor.com/v0"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.timeout = timeout
        # Reuse a Session for TCP connection pooling across the many
        # polling calls per phase.  Auth and Content-Type are set once.
        self.session = requests.Session()
        self.session.auth = (api_key, "")  # Basic Auth: key as username, empty password
        self.session.headers.update({"Content-Type": "application/json"})

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """HTTP request with retry and exponential backoff.

        Retries on both retryable HTTP status codes and connection-level
        errors (``ConnectionError``, ``Timeout``).  A per-request timeout
        prevents indefinite hangs.  Uses a persistent ``Session`` for TCP
        connection reuse.
        """
        kwargs.setdefault("timeout", self.timeout)
        r: requests.Response | None = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                wait = BASE_BACKOFF * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "%s from %s (attempt %d/%d), waiting %.1fs",
                    type(exc).__name__,
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                    wait,
                )
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(wait)
                continue
            if r.status_code not in RETRYABLE_STATUS_CODES:
                r.raise_for_status()
                return r
            wait = BASE_BACKOFF * (2**attempt) + random.uniform(0, 1)
            logger.warning(
                "Retryable %d from %s (attempt %d/%d), waiting %.1fs",
                r.status_code,
                url,
                attempt + 1,
                MAX_RETRIES,
                wait,
            )
            time.sleep(wait)
        assert r is not None
        r.raise_for_status()  # Final attempt failed — raise
        return r  # unreachable, but satisfies type checker

    def launch(
        self,
        prompt: str,
        repo: str,
        ref: str,
        model: str | None = None,
    ) -> dict:
        """Launch a new cloud agent with the given prompt and repo context.

        Parameters
        ----------
        repo:
            Full GitHub URL (``https://github.com/owner/repo``) or
            shorthand ``owner/repo`` (automatically expanded).
        """
        if not repo.startswith("https://"):
            repo = f"https://github.com/{repo}"
        body: dict = {
            "prompt": {"text": prompt},
            "source": {"repository": repo, "ref": ref},
        }
        if model:
            body["model"] = model
        return self._request("POST", f"{self.BASE}/agents", json=body).json()

    def followup(self, agent_id: str, prompt: str) -> dict:
        """Send a follow-up message to an existing agent."""
        return self._request(
            "POST",
            f"{self.BASE}/agents/{agent_id}/followup",
            json={"prompt": {"text": prompt}},
        ).json()

    def status(self, agent_id: str) -> dict:
        """Get the current status of an agent."""
        return self._request("GET", f"{self.BASE}/agents/{agent_id}").json()

    def get_conversation(self, agent_id: str) -> list[dict]:
        """Retrieve the full conversation history for an agent."""
        r = self._request("GET", f"{self.BASE}/agents/{agent_id}/conversation")
        return r.json().get("messages", [])

    def stop(self, agent_id: str) -> dict:
        """Stop a running agent (can be resumed with a follow-up)."""
        return self._request("POST", f"{self.BASE}/agents/{agent_id}/stop").json()

    def delete(self, agent_id: str) -> dict:
        """Permanently delete an agent."""
        return self._request("DELETE", f"{self.BASE}/agents/{agent_id}").json()

    def list_agents(self, limit: int = 20, cursor: str | None = None) -> dict:
        """List all cloud agents for the authenticated user."""
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", f"{self.BASE}/agents", params=params).json()

    def me(self) -> dict:
        """Retrieve information about the current API key."""
        return self._request("GET", f"{self.BASE}/me").json()

    def list_models(self) -> list[str]:
        """Retrieve the list of recommended models for cloud agents."""
        return self._request("GET", f"{self.BASE}/models").json().get("models", [])

    def list_repositories(self) -> list[dict]:
        """List GitHub repositories accessible to the authenticated user.

        Warning: this endpoint has strict rate limits (1/user/minute).
        """
        return (
            self._request("GET", f"{self.BASE}/repositories")
            .json()
            .get("repositories", [])
        )


def wait_for_agent(
    api: CursorCloudAPI,
    agent_id: str,
    timeout: int = 600,
    poll_interval: int = 10,
) -> str:
    """Poll a single agent until FINISHED.

    Use this for initial agent launches where the status starts at
    CREATING and progresses to FINISHED.  For follow-ups, use
    :func:`wait_for_followup` instead.
    """
    start = time.time()
    while time.time() - start < timeout:
        info = api.status(agent_id)
        status = info["status"]
        if status == "FINISHED":
            return status
        if status not in ("CREATING", "RUNNING"):
            raise RuntimeError(f"Agent {agent_id} in unexpected state: {status}")
        _emit_poll_dot()
        time.sleep(poll_interval)
    raise TimeoutError(f"Agent {agent_id} did not finish within {timeout}s")


def wait_for_all_agents(
    api: CursorCloudAPI,
    agents: dict[str, str],
    timeout: int = 600,
    poll_interval: int = 10,
) -> None:
    """Poll multiple agents concurrently until all are FINISHED.

    Use this for initial agent launches.  For follow-ups, use
    :func:`wait_for_all_followups` instead.
    """
    start = time.time()
    remaining = dict(agents)
    while remaining and time.time() - start < timeout:
        for alias, agent_id in list(remaining.items()):
            info = api.status(agent_id)
            status = info["status"]
            if status == "FINISHED":
                remaining.pop(alias)
                logger.info("Agent %s (%s) finished", alias, agent_id)
            elif status not in ("CREATING", "RUNNING"):
                raise RuntimeError(f"Agent {agent_id} in unexpected state: {status}")
        if remaining:
            _emit_poll_dot()
            time.sleep(poll_interval)
    if remaining:
        raise TimeoutError(f"Agents {list(remaining)} did not finish within {timeout}s")


# ---------------------------------------------------------------------------
# Follow-up waiting helpers
#
# After sending a follow-up to a FINISHED agent, there is a race: the
# status may still read FINISHED before the agent transitions to RUNNING.
# Polling status alone would return immediately with stale results.
#
# These helpers solve the race by checking for *new messages* in the
# conversation (the reliable signal), with status as a secondary check
# for error detection and a grace period for the edge case where the
# follow-up is processed before the first poll.
# ---------------------------------------------------------------------------


def wait_for_followup(
    api: CursorCloudAPI,
    agent_id: str,
    previous_msg_count: int,
    timeout: int = 600,
    poll_interval: int = 10,
    grace_period: int = 30,
) -> str:
    """Wait for a new assistant response after sending a follow-up.

    Parameters
    ----------
    previous_msg_count:
        Number of messages in the conversation *before* the follow-up was
        sent.  Obtained via ``len(api.get_conversation(agent_id))``.
    grace_period:
        Seconds to tolerate the agent remaining FINISHED with no new
        messages.  Covers the window between the POST returning and the
        agent status transitioning to RUNNING.
    """
    start = time.time()
    grace_deadline: float | None = None

    while time.time() - start < timeout:
        # Primary signal: new assistant message
        messages = api.get_conversation(agent_id)
        if len(messages) > previous_msg_count and is_assistant_message(messages[-1]):
            return "FINISHED"

        # Secondary signal: agent status (for error detection + grace)
        info = api.status(agent_id)
        status = info["status"]

        if status in ("RUNNING", "CREATING"):
            grace_deadline = None  # Agent is working — reset grace
        elif status == "FINISHED":
            if grace_deadline is None:
                grace_deadline = time.time() + grace_period
                logger.debug(
                    "Agent %s FINISHED with no new messages, starting %ds grace period",
                    agent_id,
                    grace_period,
                )
            elif time.time() >= grace_deadline:
                # Final check before giving up
                messages = api.get_conversation(agent_id)
                if len(messages) > previous_msg_count and is_assistant_message(
                    messages[-1]
                ):
                    return "FINISHED"
                raise RuntimeError(
                    f"Agent {agent_id} remained FINISHED for {grace_period}s "
                    f"with no new messages (had {previous_msg_count}, "
                    f"got {len(messages)})"
                )
        else:
            raise RuntimeError(f"Agent {agent_id} in unexpected state: {status}")

        _emit_poll_dot()
        time.sleep(poll_interval)

    raise TimeoutError(f"Agent {agent_id}: no new response within {timeout}s")


def wait_for_all_followups(
    api: CursorCloudAPI,
    agents: dict[str, tuple[str, int]],
    timeout: int = 600,
    poll_interval: int = 10,
    grace_period: int = 30,
) -> None:
    """Wait for new assistant responses from multiple agents after follow-ups.

    Parameters
    ----------
    agents:
        Mapping of ``alias -> (agent_id, previous_msg_count)``.
    """
    start = time.time()
    remaining = dict(agents)
    grace_deadlines: dict[str, float] = {}

    while remaining and time.time() - start < timeout:
        for alias, (agent_id, prev_count) in list(remaining.items()):
            messages = api.get_conversation(agent_id)
            if len(messages) > prev_count and is_assistant_message(messages[-1]):
                remaining.pop(alias)
                grace_deadlines.pop(alias, None)
                logger.info("Agent %s (%s) responded", alias, agent_id)
                continue

            info = api.status(agent_id)
            status = info["status"]

            if status in ("RUNNING", "CREATING"):
                grace_deadlines.pop(alias, None)
            elif status == "FINISHED":
                if alias not in grace_deadlines:
                    grace_deadlines[alias] = time.time() + grace_period
                elif time.time() >= grace_deadlines[alias]:
                    messages = api.get_conversation(agent_id)
                    if len(messages) > prev_count and is_assistant_message(
                        messages[-1]
                    ):
                        remaining.pop(alias)
                        grace_deadlines.pop(alias, None)
                        continue
                    raise RuntimeError(
                        f"Agent {alias} ({agent_id}) remained FINISHED for "
                        f"{grace_period}s with no new messages "
                        f"(had {prev_count}, got {len(messages)})"
                    )
            else:
                raise RuntimeError(
                    f"Agent {alias} ({agent_id}) in unexpected state: {status}"
                )

        if remaining:
            _emit_poll_dot()
            time.sleep(poll_interval)

    if remaining:
        raise TimeoutError(
            f"Agents {list(remaining)} did not respond within {timeout}s"
        )
