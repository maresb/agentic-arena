"""Cursor Cloud Agents API wrapper with retry and exponential backoff."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

logger = logging.getLogger("arena")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
BASE_BACKOFF = 2.0  # seconds


class CursorCloudAPI:
    """HTTP client for the Cursor Cloud Agents API."""

    BASE = "https://api.cursor.com/v0"

    def __init__(self, api_key: str) -> None:
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """HTTP request with retry and exponential backoff."""
        r: requests.Response | None = None
        for attempt in range(MAX_RETRIES):
            r = requests.request(method, url, headers=self.headers, **kwargs)
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
        """Launch a new cloud agent with the given prompt and repo context."""
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


def wait_for_agent(
    api: CursorCloudAPI,
    agent_id: str,
    timeout: int = 600,
    poll_interval: int = 10,
) -> str:
    """Poll a single agent until FINISHED."""
    start = time.time()
    while time.time() - start < timeout:
        info = api.status(agent_id)
        status = info["status"]
        if status == "FINISHED":
            return status
        if status not in ("CREATING", "RUNNING"):
            raise RuntimeError(f"Agent {agent_id} in unexpected state: {status}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Agent {agent_id} did not finish within {timeout}s")


def wait_for_all_agents(
    api: CursorCloudAPI,
    agents: dict[str, str],
    timeout: int = 600,
    poll_interval: int = 10,
) -> None:
    """Poll multiple agents concurrently until all are FINISHED."""
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
                raise RuntimeError(
                    f"Agent {agent_id} in unexpected state: {status}"
                )
        if remaining:
            time.sleep(poll_interval)
    if remaining:
        raise TimeoutError(
            f"Agents {list(remaining)} did not finish within {timeout}s"
        )
