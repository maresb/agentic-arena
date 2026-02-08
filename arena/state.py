"""State management for the arena orchestrator.

All arena state lives in a single JSON file backed by Pydantic models.
The orchestrator is stateless: it reads the state file, performs one step,
writes the updated state, and can be killed and restarted at any point
without losing progress.
"""

from __future__ import annotations

import json
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

    # Per-agent message counts recorded when follow-ups are sent.
    # Used for message-count-based waiting on resume after a crash,
    # preventing stale-message extraction when an agent is already
    # FINISHED from a previous task.
    #
    # TODO: if per-agent metadata grows beyond sent_msg_counts (e.g.,
    # tracking sent phase, retry counts), refactor into a FollowupMeta
    # nested Pydantic model keyed by alias.
    sent_msg_counts: dict[str, int] = Field(default_factory=dict)

    # Verify-phase idempotency: persisted so a crash between sending the
    # verify follow-up and completing extraction doesn't re-select a judge
    # or send a duplicate prompt on restart.
    verify_judge: str | None = None
    verify_prev_msg_count: int | None = None

    # Verify command outputs: stored as first-class data so the report
    # can include them and failures can optionally veto consensus.
    verify_results: list[str] = Field(default_factory=list)

    # Agent branch names: captured from the launch API response so that
    # agents can inspect each other's committed work via git fetch.
    branch_names: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


_FILE_REF_PREFIX = "file:"

# Fields whose dict values are externalized to separate .md files.
_EXTERNALIZABLE_DICT_FIELDS = ("solutions", "analyses", "critiques")

# Fields whose list values are externalized (verify_results).
_EXTERNALIZABLE_LIST_FIELDS = ("verify_results",)


def _resolve_file_ref(value: str, base_dir: str) -> str:
    """If *value* is a ``file:`` reference, read and return the file content."""
    if value.startswith(_FILE_REF_PREFIX):
        rel = value[len(_FILE_REF_PREFIX) :]
        file_path = os.path.join(base_dir, rel)
        if os.path.exists(file_path):
            with open(file_path) as f:
                return f.read()
        logger.warning("Externalized file %s not found; using empty string", file_path)
        return ""
    return value


def _write_artifact(content: str, artifact_path: str) -> None:
    """Write artifact content to disk."""
    os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
    with open(artifact_path, "w") as f:
        f.write(content)


def load_state(path: str = "arena/state.json") -> ArenaState | None:
    """Load arena state from disk. Returns ``None`` if the file does not exist.

    Transparently resolves ``file:`` references back to inline text so
    that phase functions always see plain strings.  Handles both the old
    inline format and the new externalized format (migration shim).
    """
    if not os.path.exists(path):
        return None
    with open(path) as f:
        raw = f.read()
    state = ArenaState.model_validate_json(raw)

    base_dir = os.path.dirname(path) or "."

    # Resolve dict fields (solutions, analyses, critiques)
    for field_name in _EXTERNALIZABLE_DICT_FIELDS:
        d: dict[str, str] = getattr(state, field_name)
        for key, value in d.items():
            d[key] = _resolve_file_ref(value, base_dir)

    # Resolve list fields (verify_results)
    for field_name in _EXTERNALIZABLE_LIST_FIELDS:
        lst: list[str] = getattr(state, field_name)
        for i, value in enumerate(lst):
            lst[i] = _resolve_file_ref(value, base_dir)

    # Resolve final_verdict
    if state.final_verdict:
        state.final_verdict = _resolve_file_ref(state.final_verdict, base_dir)

    return state


def save_state(state: ArenaState, path: str = "arena/state.json") -> None:
    """Atomic write: write to temp file then rename to prevent corruption.

    Large text fields are externalized to separate ``.md`` files under an
    ``artifacts/`` subdirectory.  The JSON stores ``file:`` references
    instead of inline text.
    """
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    artifacts_dir = os.path.join(parent, "artifacts")

    # Build a shallow copy with file references replacing large text
    dump = state.model_dump()

    # Externalize dict fields
    for field_name in _EXTERNALIZABLE_DICT_FIELDS:
        d = dump.get(field_name, {})
        for key, value in d.items():
            if value:
                rel = f"artifacts/{field_name}_{key}.md"
                _write_artifact(value, os.path.join(parent, rel))
                d[key] = f"{_FILE_REF_PREFIX}{rel}"

    # Externalize list fields
    for field_name in _EXTERNALIZABLE_LIST_FIELDS:
        lst = dump.get(field_name, [])
        for i, value in enumerate(lst):
            if value:
                rel = f"artifacts/{field_name}_{i}.md"
                _write_artifact(value, os.path.join(parent, rel))
                lst[i] = f"{_FILE_REF_PREFIX}{rel}"

    # Externalize final_verdict
    if dump.get("final_verdict"):
        rel = "artifacts/final_verdict.md"
        _write_artifact(dump["final_verdict"], os.path.join(parent, rel))
        dump["final_verdict"] = f"{_FILE_REF_PREFIX}{rel}"

    json_str = json.dumps(dump, indent=2)

    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json_str)
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
