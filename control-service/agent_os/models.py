"""Core domain models for the Agent OS control service (skeleton).

Authority split (AGENT-OS-HANDOFF.md section 7):
- PLANNER (e.g. Hermes) may only propose.
- HUMAN is the only principal that may decide approvals (no self-approval).
- WORKER (e.g. DSH) only executes what dispatch hands it.
- The deterministic service is the only writer of authoritative state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class CommandFormatError(ValueError):
    """The stored `command` is not a readable canonical JSON argv array.

    Raised instead of letting a json/TypeError escape, because a row written by
    an older build may hold anything at all. Callers must fail closed on it.
    """


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def encode_command(argv: Optional[list]) -> Optional[str]:
    """Serialize an argv list to the canonical JSON string stored in the DB.

    Why a JSON string and not a joined command line: the column is TEXT and
    sqlite refuses to bind a list, while `shell=False` Popen refuses anything
    that is not a list. A canonical JSON string is the one representation that
    satisfies the storage layer without inventing a quoting/parsing rule, and
    it is stable enough to hash - which is what the Phase 5 requirement
    ("changing a parameter requires a fresh approval") needs.

    Canonical means separators=(",", ":") with no spaces, so the same argv
    always produces byte-identical output and therefore a stable manifest
    hash. ensure_ascii=False keeps non-ASCII arguments readable; it does not
    affect determinism because the input str is the same either way.

    None in, None out: an absent command stays absent, so the executor's own
    fail-closed path (not a decode error) is what reports it.
    """
    if argv is None:
        return None
    if not isinstance(argv, list):
        raise TypeError(
            f"encode_command expects a list or None; got {type(argv).__name__}"
        )
    return json.dumps(argv, separators=(",", ":"), ensure_ascii=False)


def decode_command(stored: Optional[str]) -> Optional[list]:
    """Parse a stored `command` back into argv, or raise CommandFormatError.

    The migration contract: a row written before this fix may hold a value
    json.loads cannot read. That is not an internal error, it is a refusal, so
    it gets a named exception with a message an operator can act on rather
    than a traceback from three frames down.

    Shape is re-checked here, not merely parsed. `json.loads("1")` succeeds
    and would hand Popen an int; `json.loads('"echo hi"')` succeeds and would
    make Popen raise FileNotFoundError. Parsing is not validation.
    """
    if stored is None:
        return None
    if not isinstance(stored, str):
        raise CommandFormatError(
            f"stored command must be a JSON string; got {type(stored).__name__}"
        )
    try:
        value = json.loads(stored)
    except (ValueError, TypeError) as e:
        raise CommandFormatError(
            f"stored command is not valid JSON ({type(e).__name__}); "
            "re-propose the job to rewrite it"
        ) from e
    if not isinstance(value, list) or not value:
        raise CommandFormatError(
            "stored command must be a non-empty JSON array of strings; "
            f"got {type(value).__name__}"
        )
    for i, part in enumerate(value):
        if not isinstance(part, str) or not part.strip():
            raise CommandFormatError(
                f"stored command[{i}] must be a non-empty string; "
                f"got {type(part).__name__}"
            )
    return list(value)


class Principal(str, Enum):
    """Who is asking. Only HUMAN may decide approvals (no self-approval)."""

    HUMAN = "human"
    PLANNER = "planner"  # e.g. Hermes - proposes only
    WORKER = "worker"    # e.g. DSH - executes only
    SERVICE = "service"  # the deterministic control code itself


class MissionState(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class JobState(str, Enum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED_VERIFIED = "completed_verified"
    COMPLETED_UNVERIFIED = "completed_unverified"
    FAILED = "failed"
    # Worker lost after (possibly) taking effect. Stays unknown until a
    # human reconciles it. Never auto-marked successful, never auto-rerun.
    INTERRUPTED_UNKNOWN = "interrupted_unknown"


class ApprovalDecision(str, Enum):
    REQUESTED = "requested"
    GRANTED = "granted"
    DENIED = "denied"


@dataclass
class Mission:
    id: str
    title: str
    state: MissionState
    created_at: str


@dataclass
class Job:
    id: str
    mission_id: str
    title: str
    proposed_by: Principal
    executor: str  # adapter/destination identity, e.g. "fake-executor", later "dsh"
    workspace_paths: tuple[str, ...]
    actions: tuple[str, ...]  # requested tool actions
    state: JobState
    attempt_no: int
    manifest_hash: str
    created_at: str
    updated_at: str
    # Concrete command for executors that need one (e.g. the subprocess
    # executor), stored as a canonical JSON argv string - see encode_command.
    # Included in the manifest hash: changing it invalidates any existing
    # grant (a new decision is required). Callers pass an argv LIST and the
    # service encodes it; do not hand-build this string.
    command: Optional[str] = None

    def compute_manifest_hash(self) -> str:
        """Binds an approval to the exact request it approved."""
        payload = json.dumps(
            {
                "mission_id": self.mission_id,
                "title": self.title,
                "executor": self.executor,
                "workspace_paths": list(self.workspace_paths),
                "actions": list(self.actions),
                "command": self.command,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ApprovalScope:
    """What the human was actually shown and agreed to.

    Two kinds of field live here, and the difference is load-bearing:

    - BOUNDS (executor, workspace_paths, actions) are ceilings. A caller may
      propose a wider ceiling; the human sees it and can refuse.
    - THE PAYLOAD (command) is the operation itself. It is never caller-set: it
      is copied from the job by the service. A caller who could set it could
      make the scope and the job disagree, and the human only ever sees one of
      them - so one of the two would be a lie.

    command is Optional and defaults to None so an approval row written before
    this field existed still loads. Absent means "this approval authorized no
    command", which is exactly what such a row did say at the time; it is not
    treated as a wildcard.
    """

    executor: str
    workspace_paths: tuple[str, ...]
    actions: tuple[str, ...]
    command: Optional[str] = None


@dataclass
class Approval:
    id: str
    job_id: str
    decision: ApprovalDecision
    scope: ApprovalScope
    requested_at: str
    decided_at: Optional[str]
    decided_by: Optional[Principal]
    expires_at: Optional[datetime]
    manifest_hash: str


class ProjectRejected(Exception):
    """A project root was refused. Carries a machine-readable reason.

    Distinct from ValueError because the HTTP layer must map the reason to a
    status: a malformed path is a bad request, a path already registered is a
    conflict. Callers branch on .reason, never on the message.
    """

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass
class Project:
    id: str
    name: str
    environment: str
    root: str
    canonical_root: str
    is_symlink: bool
    read_only: bool
    created_at: str


class ToolRejected(Exception):
    """A tool registration was refused. Carries a machine-readable reason so
    the HTTP layer can map it to a status, exactly as ProjectRejected does."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass
class Tool:
    """A tool the owner has reviewed and recorded.

    `grants_execution` is a constant False, not a stored flag that could be set
    later: discovery is a report, and registration is a record of what the owner
    saw. Nothing in the executor consults this table, and the field exists so
    that any future code reading it has to answer for itself.

    `confidence` is carried through from discovery unchanged, including
    "unknown". It is not upgraded by registration.
    """

    id: str
    name: str
    environment: str
    path: Optional[str]
    version: Optional[str]
    confidence: str
    created_at: str

    grants_execution: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "environment": self.environment,
            "path": self.path,
            "version": self.version,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "grants_execution": self.grants_execution,
        }


@dataclass
class WorkerOutcome:
    """What an executor reports back. Claimed, not trusted: the service
    verifies required evidence before any state becomes 'verified'."""

    status: str  # "completed_with_evidence" | "completed_missing_evidence"
    evidence: dict = field(default_factory=dict)


@dataclass
class DispatchReceipt:
    job_id: str
    attempt: int
    final_state: JobState
    duplicated: bool = False  # True = idempotent re-dispatch, nothing executed


class WorkerLostError(Exception):
    """Executor disappeared after (possibly) taking effect. Outcome unknown."""


class ConflictError(Exception):
    """Knowledge edit based on a stale revision."""


class DispatchRefused(Exception):
    """Policy denied dispatch BEFORE the executor was invoked."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
