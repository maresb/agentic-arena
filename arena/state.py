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
import re
import tempfile
from enum import StrEnum
from pathlib import Path

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


# Known model short names. Any string is accepted by --models; these are the
# defaults and the keys used in the MODELS mapping in prompts.py.
DEFAULT_MODELS: tuple[str, ...] = ("opus", "gpt", "gemini")


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
    models: list[str] = Field(default_factory=lambda: list(DEFAULT_MODELS))
    branch_only: bool = False
    verify_mode: str = Field(default="advisory", pattern=r"^(advisory|gating)$")
    context_mode: str = "full"  # "full" (paste all), "diff" (git diff only), "fresh" (new agents each round)


class ArenaState(BaseModel):
    """Full arena state, persisted to disk as JSON.

    Mutable — phase functions update fields in place and call
    :func:`save_state` after every meaningful step.
    """

    config: ArenaConfig
    alias_mapping: dict[str, str]
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

    # Verify-phase tracking: separate from per-agent phase_progress
    verify_progress: ProgressStatus = ProgressStatus.PENDING

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

    # Token usage tracking: cumulative per-alias totals
    token_usage: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


_FILE_REF_PREFIX = "file:"

# Fields whose dict values are externalized to separate .md files.
_EXTERNALIZABLE_DICT_FIELDS = ("solutions", "analyses", "critiques")

# Fields whose list values are externalized (verify_results).
_EXTERNALIZABLE_LIST_FIELDS = ("verify_results",)


def _resolve_file_ref(value: str, base_dir: str) -> str:
    """If *value* is a ``file:`` reference, read and return the file content.

    Path traversal is prevented by resolving both *base_dir* and the
    joined path to absolute paths, then checking containment with
    :meth:`pathlib.Path.is_relative_to`.
    """
    if value.startswith(_FILE_REF_PREFIX):
        rel = value[len(_FILE_REF_PREFIX) :]
        resolved_base = Path(base_dir).resolve()
        resolved_path = (resolved_base / rel).resolve()
        if not resolved_path.is_relative_to(resolved_base):
            logger.warning("Path traversal blocked: %s", rel)
            return ""
        if resolved_path.exists():
            return resolved_path.read_text()
        logger.warning(
            "Externalized file %s not found; using empty string", resolved_path
        )
        return ""
    return value


def _write_artifact(content: str, artifact_path: str) -> None:
    """Atomically write artifact content to disk (temp + rename)."""
    parent = os.path.dirname(artifact_path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, artifact_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            # Best-effort cleanup: ignore errors when deleting the temp file.
            pass
        raise


def sanitize_filename_component(name: str) -> str:
    """Sanitize a string for safe use as a filename component.

    Replaces path separators, ``..``, and other unsafe characters with
    underscores.  Returns ``"_"`` if the result would be empty.
    """
    # Replace path separators and null bytes
    sanitized = re.sub(r"[/\\:\x00]", "_", name)
    # Collapse any ".." sequences
    sanitized = sanitized.replace("..", "_")
    # Strip leading/trailing whitespace and dots
    sanitized = sanitized.strip(" .")
    return sanitized or "_"


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

    # Build a shallow copy with file references replacing large text
    dump = state.model_dump()

    # Externalize dict fields
    for field_name in _EXTERNALIZABLE_DICT_FIELDS:
        d = dump.get(field_name, {})
        for key, value in d.items():
            if value:
                safe_key = sanitize_filename_component(key)
                rel = f"artifacts/{field_name}_{safe_key}.md"
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


def _aliases_for_count(n: int) -> list[str]:
    """Generate alias names for *n* agents: agent_a, agent_b, ..., agent_z.

    Raises :class:`ValueError` if *n* exceeds 26 (a-z).
    """
    if n > 26:
        raise ValueError(f"Maximum 26 agents supported, got {n}")
    return [f"agent_{chr(ord('a') + i)}" for i in range(n)]


def init_state(
    task: str,
    repo: str,
    base_branch: str = "main",
    max_rounds: int = 3,
    verify_commands: list[str] | None = None,
    models: list[str] | None = None,
    branch_only: bool = False,
    verify_mode: str = "advisory",
) -> ArenaState:
    """Create a fresh arena state with randomized alias-to-model mapping.

    Parameters
    ----------
    models:
        Optional list of model short names (e.g. ``["opus", "gpt"]``).
        Defaults to :data:`DEFAULT_MODELS`.  Dynamically sizes the alias
        list to match.
    """
    model_list = list(models) if models else list(DEFAULT_MODELS)
    random.shuffle(model_list)
    aliases = _aliases_for_count(len(model_list))

    config = ArenaConfig(
        task=task,
        repo=repo,
        base_branch=base_branch,
        max_rounds=max_rounds,
        verify_commands=verify_commands or [],
        models=model_list,
        branch_only=branch_only,
        verify_mode=verify_mode,
    )

    return ArenaState(
        config=config,
        alias_mapping={a: m for a, m in zip(aliases, model_list)},
        phase_progress={a: ProgressStatus.PENDING for a in aliases},
    )
