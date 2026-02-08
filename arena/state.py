"""State management for the arena orchestrator.

All arena state lives in a single JSON file. The orchestrator is stateless:
it reads the state file, performs one step, writes the updated state, and
can be killed and restarted at any point without losing progress.
"""

import json
import logging
import os
import random
import tempfile

logger = logging.getLogger("arena")

ALIASES = ["agent_a", "agent_b", "agent_c"]


def load_state(path: str = "arena/state.json") -> dict | None:
    """Load arena state from disk. Returns None if the file does not exist."""
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def save_state(state: dict, path: str = "arena/state.json") -> None:
    """Atomic write: write to temp file then rename to prevent corruption."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def init_state(
    task: str,
    repo: str,
    base_branch: str = "main",
    max_rounds: int = 3,
    verify_commands: list[str] | None = None,
) -> dict:
    """Create a fresh arena state with randomized alias-to-model mapping."""
    models = ["opus", "gpt", "gemini"]
    random.shuffle(models)
    aliases = list(ALIASES)
    return {
        "task": task,
        "repo": repo,
        "base_branch": base_branch,
        "max_rounds": max_rounds,
        "verify_commands": verify_commands or [],
        "alias_mapping": dict(zip(aliases, models)),
        "agent_ids": {},
        "round": 0,
        "phase": "solve",
        "phase_progress": {a: "pending" for a in aliases},
        "solutions": {},
        "analyses": {},
        "critiques": {},
        "judge_history": [],
        "completed": False,
        "consensus_reached": None,
        "final_verdict": None,
    }
