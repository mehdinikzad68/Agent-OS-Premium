"""Core domain models for the Agent OS control service (skeleton).

Authority split (AGENT-OS-HANDOFF.md section 7):
- PLANNER (e.g. Hermes) may only propose.
- HUMAN is the only principal that may decide approvals.
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


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
    # Optional concrete command for executors that need one (e.g. the
    # subprocess executor). Included in the manifest hash: changing it
    # invalidates any existing grant (a new decision is required).
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
    executor: str
    workspace_paths: tuple[str, ...]
    actions: tuple[str, ...]


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
