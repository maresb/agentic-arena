"""State management for the arena orchestrator.

All arena state is stored in a YAML file (``state.yaml``) backed by
Pydantic models.  The orchestrator is stateless: it reads the state
file, performs one step, writes the updated state, and can be killed
and restarted at any point without losing progress.

State machine:  Solve -> Evaluate -> Done  (if consensus)
                                  -> Revise -> Evaluate -> ...
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import tempfile
from enum import StrEnum
from io import StringIO
from pathlib import Path

from pydantic import BaseModel, Field
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

logger = logging.getLogger("arena")

ALIASES = ["agent_a", "agent_b", "agent_c"]

# Default placeholder task text.  ``init`` uses this when ``--task`` is
# omitted; ``step`` and ``run`` refuse to proceed while the task is still
# set to this value.
TASK_PLACEHOLDER = "[DESCRIBE THE TASK HERE]"

# Phase name → phase number, used in file naming.
PHASE_NUMBERS: dict[str, int] = {"solve": 1, "evaluate": 2, "revise": 3}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Phase(StrEnum):
    """Arena phase in the consensus loop.

    3-phase design: Solve -> Evaluate (critique + vote) -> Revise.
    Evaluate and Verify are collapsed into a single Evaluate phase.
    """

    SOLVE = "solve"
    EVALUATE = "evaluate"
    REVISE = "revise"
    DONE = "done"


class ProgressStatus(StrEnum):
    """Per-agent progress within a phase."""

    PENDING = "pending"
    SENT = "sent"
    DONE = "done"


# Known model short names. Any string is accepted by --models; these are the
# defaults and the keys used in the DEFAULT_MODEL_NICKNAMES mapping below.
DEFAULT_MODELS: tuple[str, ...] = ("opus", "gpt", "gemini")

# Default mapping of short nicknames to full API model identifiers.
# Used as the default value for ``model_nicknames`` in :func:`init_state`.
# Any nickname not found in the mapping is used as-is (pass-through).
DEFAULT_MODEL_NICKNAMES: dict[str, str] = {
    "opus": "claude-4.6-opus-high-thinking",
    "gpt": "gpt-5.2-codex-high",
    "gemini": "gemini-3-pro",
}


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
    verify_mode: str = Field(default="advisory", pattern=r"^(advisory|gating)$")
    arena_number: int = Field(default=1, ge=1)


class ArenaState(BaseModel):
    """Full arena state, persisted to disk as YAML.

    Mutable — phase functions update fields in place and call
    :func:`save_state` after every meaningful step.
    """

    config: ArenaConfig
    alias_mapping: dict[str, str]

    # Nickname → full API model name.  ``alias_mapping`` values are looked
    # up here when the real model identifier is needed (e.g. API launch).
    # A value not present in this dict is used as-is (pass-through).
    model_nicknames: dict[str, str] = Field(default_factory=dict)

    agent_ids: dict[str, str] = Field(default_factory=dict)
    round: int = 0
    phase: Phase = Phase.SOLVE
    phase_progress: dict[str, ProgressStatus] = Field(default_factory=dict)
    solutions: dict[str, str] = Field(default_factory=dict)
    analyses: dict[str, str] = Field(default_factory=dict)
    critiques: dict[str, str] = Field(default_factory=dict)
    completed: bool = False
    consensus_reached: bool | None = None
    final_verdict: str | None = None

    # Per-agent message counts recorded when follow-ups are sent.
    # Used for message-count-based waiting on resume after a crash.
    sent_msg_counts: dict[str, int] = Field(default_factory=dict)

    # Verify command outputs: stored as first-class data so the report
    # can include them and failures can optionally veto consensus.
    verify_results: list[str] = Field(default_factory=list)

    # Agent branch names: captured from the status API response so that
    # agents can inspect each other's committed work via git fetch.
    branch_names: dict[str, str] = Field(default_factory=dict)

    # Token usage tracking: cumulative per-alias totals
    token_usage: dict[str, int] = Field(default_factory=dict)

    # Verdict history: accumulates verdict JSON strings for every evaluate
    # round (including CONTINUE rounds).  Preserves intermediate verdicts.
    verdict_history: list[str] = Field(default_factory=list)

    # Per-agent timing: maps alias → {phase_name: {start: float, end: float}}.
    # Recorded as epoch timestamps from time.time().
    agent_timing: dict[str, dict[str, dict[str, float]]] = Field(default_factory=dict)

    # Per-agent metadata from the API status response (summary, linesAdded,
    # filesChanged).  Captured after the solve and revise phases complete.
    agent_metadata: dict[str, dict[str, str | int]] = Field(default_factory=dict)

    # --- Multi-agent voting (populated during evaluate phase) ---

    # Each agent's voted-for aliases (e.g. {"agent_a": ["agent_b", "agent_c"]}).
    verify_votes: dict[str, list[str]] = Field(default_factory=dict)

    # Each agent's individual convergence score (1-10).
    verify_scores: dict[str, int] = Field(default_factory=dict)

    # The elected winner alias (set when consensus is reached).
    verify_winner: str | None = None


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


def resolve_model(state: ArenaState, name: str) -> str:
    """Resolve a model nickname to its full API identifier.

    Looks up *name* in ``state.model_nicknames``, falling back to *name*
    itself when no mapping exists.  This allows ``alias_mapping`` values
    to be either nicknames (``"opus"``) or already-full identifiers
    (``"claude-4.6-opus-high-thinking"``).
    """
    return state.model_nicknames.get(name, name)


# ---------------------------------------------------------------------------
# File naming helpers
# ---------------------------------------------------------------------------


def expected_path(
    arena_number: int,
    alias: str,
    artifact: str,
    ext: str = "md",
) -> str:
    """Build the stable file path for an agent-committed output.

    Returns e.g. ``arenas/0003/agent_a-solution.md``.

    Paths are intentionally round/phase-agnostic so agents overwrite
    the same file each round, producing meaningful git diffs.
    """
    return f"arenas/{arena_number:04d}/{alias}-{artifact}.{ext}"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


_FILE_REF_PREFIX = "file:"

# Fields whose dict values are externalized to separate .md files.
_EXTERNALIZABLE_DICT_FIELDS = ("solutions", "analyses", "critiques")

# Fields whose list values are externalized (verify_results, verdict_history).
_EXTERNALIZABLE_LIST_FIELDS = ("verify_results", "verdict_history")


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


def _yaml_instance() -> YAML:
    """Create a configured YAML instance for state serialization."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.width = 120  # Wider lines for readability
    return yaml


def _resolve_state_from_dict(data: dict, base_dir: str) -> ArenaState:
    """Build an ArenaState from a parsed dict and resolve file refs."""
    state = ArenaState.model_validate(data)

    # Resolve dict fields (solutions, analyses, critiques)
    for field_name in _EXTERNALIZABLE_DICT_FIELDS:
        d: dict[str, str] = getattr(state, field_name)
        for key, value in d.items():
            d[key] = _resolve_file_ref(value, base_dir)

    # Resolve list fields (verify_results, verdict_history)
    for field_name in _EXTERNALIZABLE_LIST_FIELDS:
        lst: list[str] = getattr(state, field_name)
        for i, value in enumerate(lst):
            lst[i] = _resolve_file_ref(value, base_dir)

    # Resolve final_verdict
    if state.final_verdict:
        state.final_verdict = _resolve_file_ref(state.final_verdict, base_dir)

    return state


def load_state(path: str = "arena/state.yaml") -> ArenaState | None:
    """Load arena state from disk. Returns ``None`` if the file does not exist.

    Supports both YAML (``state.yaml``) and legacy JSON (``state.json``)
    files.  Transparently resolves ``file:`` references back to inline
    text so that phase functions always see plain strings.
    """
    # Try the requested path first, then the alternate extension
    candidates = [path]
    base, ext = os.path.splitext(path)
    if ext == ".yaml":
        candidates.append(base + ".json")
    elif ext == ".json":
        candidates.insert(0, base + ".yaml")  # prefer YAML

    actual_path: str | None = None
    for candidate in candidates:
        if os.path.exists(candidate):
            actual_path = candidate
            break
    if actual_path is None:
        return None

    base_dir = os.path.dirname(actual_path) or "."

    with open(actual_path) as f:
        raw = f.read()

    # Detect format by extension or content
    if actual_path.endswith(".yaml") or actual_path.endswith(".yml"):
        yaml = _yaml_instance()
        data = yaml.load(raw)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValueError(
                f"State file {actual_path} is malformed: expected a YAML mapping "
                f"at the top level but got {type(data).__name__!r}."
            )
        return _resolve_state_from_dict(data, base_dir)
    else:
        data = json.loads(raw)
        return _resolve_state_from_dict(data, base_dir)


def save_state(state: ArenaState, path: str = "arena/state.yaml") -> None:
    """Atomic write: write to temp file then rename to prevent corruption.

    Large text fields are externalized to separate ``.md`` files under an
    ``artifacts/`` subdirectory.  The state file stores ``file:`` references
    instead of inline text.
    """
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    # Build a shallow copy with file references replacing large text.
    # mode="json" ensures StrEnum values are serialized as plain strings
    # (required for ruamel.yaml which can't represent StrEnum directly).
    dump = state.model_dump(mode="json")

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

    # Serialize
    if path.endswith(".json"):
        serialized = json.dumps(dump, indent=2)
    else:
        # Always use literal block scalar (| / |-) for the task field so
        # it is easy to edit in the YAML file and avoids quoting issues
        # with characters like '[' that are YAML syntax.
        task_val = dump.get("config", {}).get("task", "")
        if task_val:
            dump["config"]["task"] = LiteralScalarString(task_val)
        yaml = _yaml_instance()
        stream = StringIO()
        yaml.dump(dump, stream)
        serialized = stream.getvalue()

    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(serialized)
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
    verify_mode: str = "advisory",
    arena_number: int = 1,
) -> ArenaState:
    """Create a fresh arena state with randomized alias-to-model mapping.

    Parameters
    ----------
    models:
        Optional list of model short names (e.g. ``["opus", "gpt"]``).
        Defaults to :data:`DEFAULT_MODELS`.  Dynamically sizes the alias
        list to match.
    arena_number:
        Sequential arena run number (the NNNN in ``arenas/NNNN/``).
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
        verify_mode=verify_mode,
        arena_number=arena_number,
    )

    return ArenaState(
        config=config,
        alias_mapping={a: m for a, m in zip(aliases, model_list)},
        model_nicknames=dict(DEFAULT_MODEL_NICKNAMES),
        phase_progress={a: ProgressStatus.PENDING for a in aliases},
    )
