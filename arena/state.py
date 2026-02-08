"""State management for the arena orchestrator.

All arena state lives in a single JSON file backed by Pydantic models.
The orchestrator is stateless: it reads the state file, performs one step,
writes the updated state, and can be killed and restarted at any point
without losing progress.
"""

from __future__ import annotations

import logging
import os
import random
import tempfile
from enum import StrEnum

from pydantic import BaseModel, Field

logger = logging.getLogger("arena")

ALIASES = ["agent_a", "agent_b", "agent_c"]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Phase(StrEnum):
    """Arena phase in the consensus loop."""

    SOLVE = "solve"
    EVALUATE = "evaluate"
    REVISE = "revise"
    VERIFY = "verify"
    DONE = "done"


class ProgressStatus(StrEnum):
    """Per-agent progress within a phase."""

    PENDING = "pending"
    SENT = "sent"
    DONE = "done"


class ModelName(StrEnum):
    """Supported model identifiers."""

    OPUS = "opus"
    GPT = "gpt"
    GEMINI = "gemini"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ArenaConfig(BaseModel, frozen=True):
    """Immutable configuration for an arena run.

    Set once during ``init`` and never modified afterwards.
    """

    task: str
    repo: str
    base_branch: str = "main"
    max_rounds: int = Field(default=3, ge=1, le=10)
    verify_commands: list[str] = Field(default_factory=list)


class ArenaState(BaseModel):
    """Full arena state, persisted to disk as JSON.

    Mutable — phase functions update fields in place and call
    :func:`save_state` after every meaningful step.
    """

    config: ArenaConfig
    alias_mapping: dict[str, ModelName]
    agent_ids: dict[str, str] = Field(default_factory=dict)
    round: int = 0
    phase: Phase = Phase.SOLVE
    phase_progress: dict[str, ProgressStatus] = Field(default_factory=dict)
    solutions: dict[str, str] = Field(default_factory=dict)
    analyses: dict[str, str] = Field(default_factory=dict)
    critiques: dict[str, str] = Field(default_factory=dict)
    judge_history: list[str] = Field(default_factory=list)
    completed: bool = False
    consensus_reached: bool | None = None
    final_verdict: str | None = None


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def load_state(path: str = "arena/state.json") -> ArenaState | None:
    """Load arena state from disk. Returns ``None`` if the file does not exist."""
    if os.path.exists(path):
        with open(path) as f:
            return ArenaState.model_validate_json(f.read())
    return None


def save_state(state: ArenaState, path: str = "arena/state.json") -> None:
    """Atomic write: write to temp file then rename to prevent corruption."""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(state.model_dump_json(indent=2))
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def init_state(
    task: str,
    repo: str,
    base_branch: str = "main",
    max_rounds: int = 3,
    verify_commands: list[str] | None = None,
) -> ArenaState:
    """Create a fresh arena state with randomized alias-to-model mapping."""
    models = list(ModelName)
    random.shuffle(models)
    aliases = list(ALIASES)

    config = ArenaConfig(
        task=task,
        repo=repo,
        base_branch=base_branch,
        max_rounds=max_rounds,
        verify_commands=verify_commands or [],
    )

    return ArenaState(
        config=config,
        alias_mapping=dict(zip(aliases, models)),
        phase_progress={a: ProgressStatus.PENDING for a in aliases},
    )
