"""ControlService - the deterministic state machine.

The ONLY path from an approved proposal to execution is dispatch(), and
dispatch() runs policy validation BEFORE the executor is invoked, then
persists the dispatch intent before starting work.

Acceptance criteria this service is built against (handoff section 8 /
architecture brief section 7):
  A1 restart preserves mission/approval/event state
  A2 expired approval or unapproved destination refused before dispatch
  A3 planner cannot self-approve, execute directly, or enlarge tools
  A4 missing test report can never become verified completion
  A5 lost worker stays interrupted/unknown until human reconciliation
  A6 replayed events / duplicate dispatch perform no duplicate action
  A7 knowledge edit on a stale revision raises a conflict
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .adapters.fake import FakeExecutor  # noqa: F401  (re-export for tests)
from .logging_setup import get_logger, log_event
from .paths import (
    REASON_NOT_ABSOLUTE,
    REASON_OK,
    REASON_OUTSIDE_SCOPE,
    REASON_TRAVERSAL,
    REASON_WINDOWS_UNSUPPORTED,
    canonicalize,
    check_project_root,
    is_within,
)

from .models import (
    Approval,
    ApprovalDecision,
    ApprovalScope,
    ConflictError,
    DispatchReceipt,
    DispatchRefused,
    Job,
    JobState,
    Mission,
    MissionState,
    Principal,
    Project,
    ProjectRejected,
    WorkerLostError,
    WorkerOutcome,
    iso,
    utc_now,
)
from .policy import validate_dispatch
from .store import Store, _new_id

#: Evidence keys that must be non-empty for a job to count as VERIFIED.
REQUIRED_EVIDENCE_KEYS = ("diff", "test_report")

#: Evidence strings longer than this are truncated when persisted into the
#: append-only event log (keeps events bounded; the run itself is already
#: bounded by the executor's own capture limits).
EVENT_EVIDENCE_STRING_LIMIT = 16_384


def _bounded_evidence(evidence: dict | None) -> dict:
    out: dict = {}
    for k, v in (evidence or {}).items():
        if isinstance(v, str) and len(v) > EVENT_EVIDENCE_STRING_LIMIT:
            out[k] = v[:EVENT_EVIDENCE_STRING_LIMIT] + "\n...[truncated]"
        else:
            out[k] = v
    return out


_log = get_logger("service")


PROJECT_SCOPE_ENV = "AGENT_OS_PROJECT_SCOPE"
"""Where registered project roots may live. Configuration, not a product root.

The roadmap forbids hardcoding the product root, so nothing here names a
project. When neither this variable nor the default directory exists,
registration fails closed rather than widening to the whole filesystem.
"""

REASON_SCOPE_UNSET = "scope_unset"
REASON_MISSING = "missing"
REASON_NOT_A_DIRECTORY = "not_a_directory"
REASON_NOT_READABLE = "not_readable"
REASON_SYMLINK_ESCAPE = "symlink_escapes_scope"


def project_scope() -> Optional[str]:
    """The configured allowed root, or None when there is no safe default."""
    configured = os.environ.get(PROJECT_SCOPE_ENV)
    if configured:
        return canonicalize(configured)
    default = os.path.join(os.path.expanduser("~"), "workspace")
    if os.path.isdir(default):
        return canonicalize(default)
    return None


def inspect_root(raw: str, scope: str, environment: str) -> "RootInspection":
    """Check a typed path against the real filesystem, after the lexical gate.

    Existence, type, readability and symlink escape are decided here and
    nowhere else. Nothing in this function writes, mounts, or executes: a
    registration must be inert, so the only side effect is a read.
    """
    if environment != "wsl":
        return RootInspection(False, REASON_WINDOWS_UNSUPPORTED, "", False)
    if not os.path.isabs(raw):
        return RootInspection(False, REASON_NOT_ABSOLUTE, "", False)
    if any(seg == ".." for seg in raw.split("/")):
        return RootInspection(False, REASON_TRAVERSAL, "", False)

    canonical = canonicalize(raw)
    if not is_within(scope, canonical):
        return RootInspection(False, REASON_OUTSIDE_SCOPE, canonical, False)
    if not os.path.exists(raw):
        return RootInspection(False, REASON_MISSING, canonical, False)
    if not os.path.isdir(raw):
        return RootInspection(False, REASON_NOT_A_DIRECTORY, canonical, False)
    if not os.access(raw, os.R_OK | os.X_OK):
        return RootInspection(False, REASON_NOT_READABLE, canonical, False)

    is_symlink = os.path.islink(raw)
    # Containment was proved lexically. A symlink can leave the scope while
    # every string still looks fine, so re-prove it against the resolved path.
    resolved = os.path.realpath(raw)
    if not is_within(canonicalize(scope), canonicalize(resolved)):
        return RootInspection(
            False, REASON_SYMLINK_ESCAPE, canonicalize(resolved), is_symlink
        )
    return RootInspection(True, REASON_OK, canonicalize(resolved), is_symlink)


@dataclass(frozen=True)
class RootInspection:
    """What the filesystem says about a candidate root."""

    ok: bool
    reason: str
    canonical: str
    is_symlink: bool


class ControlService:
    def __init__(self, db_path: str | Path):
        self.store = Store(db_path)

    def close(self) -> None:
        self.store.close()

    # ------------------------------------------------------------------
    # missions
    # ------------------------------------------------------------------

    # -- projects -------------------------------------------------------

    def list_projects(self) -> list[Project]:
        return self.store.list_projects()

    def register_project(
        self,
        name: str,
        environment: str,
        root: str,
        scope: Optional[str] = None,
    ) -> Project:
        """Validate a project root and record it. Read-only against the disk.

        Two gates, in this order. The lexical one is pure and cheap; the disk
        one is what sees a symlink escaping the scope. Both must pass.

        scope is a parameter rather than a lookup so a caller can register
        against an explicit root, but the default comes from configuration
        (project_scope) and never from a product path.
        """
        if scope is None:
            scope = project_scope()
        if scope is None:
            raise ProjectRejected(
                REASON_SCOPE_UNSET,
                f"set {PROJECT_SCOPE_ENV} to the directory projects may live in",
            )

        lexical = check_project_root(root, scope, environment)
        if not lexical.ok:
            raise ProjectRejected(lexical.reason, f"refused {root!r}: {lexical.reason}")

        disk = inspect_root(root, scope, environment)
        if not disk.ok:
            raise ProjectRejected(disk.reason, f"refused {root!r}: {disk.reason}")

        project = self.store.create_project(
            name=name,
            environment=environment,
            root=root,
            canonical_root=disk.canonical,
            is_symlink=disk.is_symlink,
        )
        if project is None:
            raise ProjectRejected(
                "duplicate", f"{environment}:{disk.canonical} is already registered"
            )
        self.store.record_event(
            "project_registered",
            {"project_id": project.id, "name": name, "root": disk.canonical,
             "is_symlink": disk.is_symlink},
        )
        return project

    def create_mission(self, title: str, now: Optional[datetime] = None) -> Mission:
        now = now or utc_now()
        mission = self.store.create_mission(title, now)
        self.store.record_event("mission_created", {"mission_id": mission.id, "title": title})
        log_event(_log, logging.INFO, "mission.created", mission_id=mission.id, title=title[:120])
        return mission

    def activate_mission(self, mission_id: str) -> Mission:
        self.store.update_mission_state(mission_id, MissionState.ACTIVE)
        self.store.record_event("mission_activated", {"mission_id": mission_id})
        log_event(_log, logging.INFO, "mission.activated", mission_id=mission_id)
        mission = self.store.get_mission(mission_id)
        assert mission is not None
        return mission

    # ------------------------------------------------------------------
    # job proposals (planner may propose; proposing is not executing)
    # ------------------------------------------------------------------

    def record_proposal(
        self,
        mission_id: str,
        title: str,
        executor: str,
        workspace_paths: tuple[str, ...],
        actions: tuple[str, ...],
        proposed_by: Principal,
        now: Optional[datetime] = None,
        command: Optional[str] = None,
    ) -> Job:
        if proposed_by not in (Principal.PLANNER, Principal.HUMAN):
            raise PermissionError("proposals come from planner or human only")
        now = now or utc_now()
        job = Job(
            id=_new_id("job"),
            mission_id=mission_id,
            title=title,
            proposed_by=proposed_by,
            executor=executor,
            workspace_paths=tuple(workspace_paths),
            actions=tuple(actions),
            state=JobState.PROPOSED,
            attempt_no=0,
            manifest_hash="",
            created_at=iso(now),
            updated_at=iso(now),
            command=command,
        )
        job.manifest_hash = job.compute_manifest_hash()
        self.store.insert_job(job)
        self.store.record_event(
            "job_proposed",
            {"job_id": job.id, "mission_id": mission_id, "proposed_by": proposed_by.value},
        )
        return job

    def amend_job(
        self,
        job_id: str,
        workspace_paths: Optional[tuple[str, ...]] = None,
        actions: Optional[tuple[str, ...]] = None,
        command: Optional[str] = None,
    ) -> Job:
        """Amend a proposal. Recomputes the manifest hash, which INVALIDATES
        any existing grant bound to the old hash (checked at dispatch)."""
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if workspace_paths is not None:
            job.workspace_paths = tuple(workspace_paths)
        if actions is not None:
            job.actions = tuple(actions)
        if command is not None:
            job.command = command
        job.manifest_hash = job.compute_manifest_hash()
        self.store.update_job(job_id, manifest_hash=job.manifest_hash, command=job.command)
        self.store.record_event(
            "job_amended", {"job_id": job_id, "manifest_hash": job.manifest_hash}
        )
        return job

    # ------------------------------------------------------------------
    # approvals - only HUMAN may decide (no self-approval, ever)
    # ------------------------------------------------------------------

    def request_approval(
        self,
        job_id: str,
        expires_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
        scope: Optional[ApprovalScope] = None,
    ) -> Approval:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        now = now or utc_now()
        if scope is None:
            scope = ApprovalScope(
                executor=job.executor,
                workspace_paths=job.workspace_paths,
                actions=job.actions,
            )
        approval = Approval(
            id=_new_id("appr"),
            job_id=job_id,
            decision=ApprovalDecision.REQUESTED,
            scope=scope,
            requested_at=iso(now),
            decided_at=None,
            decided_by=None,
            expires_at=expires_at,
            manifest_hash=job.manifest_hash,
        )
        self.store.insert_approval(approval)
        self.store.update_job(job_id, state=JobState.AWAITING_APPROVAL)
        self.store.record_event("approval_requested", {"approval_id": approval.id, "job_id": job_id})
        log_event(
            _log,
            logging.INFO,
            "approval.requested",
            approval_id=approval.id,
            job_id=job_id,
            executor=job.executor,
            expires_at=approval.expires_at,
        )
        return approval

    def decide(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        principal: Principal,
        now: Optional[datetime] = None,
    ) -> Approval:
        if principal is not Principal.HUMAN:
            self.store.record_event(
                "approval_decision_rejected",
                {"approval_id": approval_id, "attempted_by": principal.value},
            )
            raise PermissionError(
                f"only a human principal may decide approvals (got {principal.value})"
            )
        now = now or utc_now()
        self.store.update_approval_decision(approval_id, decision, iso(now), principal)
        approval = self.store.get_approval(approval_id)
        assert approval is not None
        if decision is ApprovalDecision.GRANTED:
            self.store.update_job(approval.job_id, state=JobState.APPROVED)
            self.store.record_event(
                "approval_granted", {"approval_id": approval_id, "job_id": approval.job_id}
            )
            log_event(
                _log,
                logging.INFO,
                "approval.granted",
                approval_id=approval_id,
                job_id=approval.job_id,
            )
        else:
            self.store.update_job(approval.job_id, state=JobState.PROPOSED)
            self.store.record_event(
                "approval_denied", {"approval_id": approval_id, "job_id": approval.job_id}
            )
            log_event(
                _log,
                logging.INFO,
                "approval.denied",
                approval_id=approval_id,
                job_id=approval.job_id,
            )
        return approval

    # ------------------------------------------------------------------
    # dispatch - deny first, persist intent, then execute
    # ------------------------------------------------------------------

    def dispatch(
        self,
        job_id: str,
        adapter,
        now: Optional[datetime] = None,
    ) -> DispatchReceipt:
        now = now or utc_now()
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)

        # A5: unknown outcome is terminal for automation; a human must reconcile.
        if job.state == JobState.INTERRUPTED_UNKNOWN:
            self.store.record_event(
                "dispatch_denied", {"job_id": job_id, "reason": "interrupted_unknown_requires_human_reconcile"}
            )
            log_event(
                _log,
                logging.WARNING,
                "dispatch.refused",
                job_id=job_id,
                reason="interrupted_unknown_requires_human_reconcile",
            )
            raise DispatchRefused("interrupted_unknown_requires_human_reconcile")

        # A6: duplicate dispatch of an in-flight/finished intent is idempotent.
        if job.state in (JobState.DISPATCHED, JobState.RUNNING) or job.state in (
            JobState.COMPLETED_VERIFIED, JobState.COMPLETED_UNVERIFIED, JobState.FAILED
        ):
            return DispatchReceipt(
                job_id=job_id, attempt=job.attempt_no, final_state=job.state, duplicated=True
            )

        # A2: policy validation BEFORE the executor is ever touched.
        approval = self.store.latest_approval_for_job(job_id)
        denial = validate_dispatch(job, approval, now)
        if denial is not None:
            self.store.record_event("dispatch_denied", {"job_id": job_id, "reason": denial})
            log_event(
                _log,
                logging.WARNING,
                "dispatch.refused",
                job_id=job_id,
                reason=denial,
            )
            raise DispatchRefused(denial)

        # A3: the adapter's tool inventory is fixed; proposals cannot enlarge it.
        unsupported = [a for a in job.actions if a not in adapter.allowed_actions]
        if unsupported:
            reason = "actions_not_supported_by_executor:" + ",".join(unsupported)
            self.store.record_event("dispatch_denied", {"job_id": job_id, "reason": reason})
            log_event(
                _log,
                logging.WARNING,
                "dispatch.refused",
                job_id=job_id,
                reason=reason,
            )
            raise DispatchRefused(reason)

        # Persist the dispatch intent BEFORE invoking the executor.
        attempt = job.attempt_no + 1
        self.store.update_job(job_id, state=JobState.DISPATCHED, attempt_no=attempt)
        self.store.record_event(
            "dispatched",
            {"job_id": job_id, "attempt": attempt, "executor": job.executor},
            dedup_key=f"dispatch:{job_id}:{attempt}",
        )
        self.store.update_job(job_id, state=JobState.RUNNING)
        log_event(
            _log,
            logging.INFO,
            "dispatch.started",
            job_id=job_id,
            attempt=attempt,
            executor=job.executor,
            actions=list(job.actions),
        )

        try:
            outcome: WorkerOutcome = adapter.run(job, attempt)
        except WorkerLostError:
            # A5: the worker may already have taken effect. Unknown, not failed,
            # not successful, and never automatically retried.
            self.store.update_job(job_id, state=JobState.INTERRUPTED_UNKNOWN)
            self.store.record_event(
                "worker_lost", {"job_id": job_id, "attempt": attempt}
            )
            log_event(
                _log,
                logging.ERROR,
                "dispatch.worker_lost",
                exc_info=True,
                job_id=job_id,
                attempt=attempt,
            )
            updated = self.store.get_job(job_id)
            assert updated is not None
            return DispatchReceipt(
                job_id=job_id, attempt=attempt, final_state=updated.state
            )

        # A4: claims are verified against required evidence before the state
        # may be called "verified". A missing test report can never pass.
        # The evidence itself is PERSISTED in the completion event so it
        # survives restarts and page reloads (durable evidence workflow).
        if outcome.status == "completed_with_evidence" and self._evidence_satisfies(outcome):
            log_event(
                _log,
                logging.INFO,
                "job.completed_verified",
                job_id=job_id,
                attempt=attempt,
            )
            self.store.update_job(job_id, state=JobState.COMPLETED_VERIFIED)
            self.store.record_event(
                "job_completed_verified",
                {"job_id": job_id, "attempt": attempt,
                 "evidence": _bounded_evidence(outcome.evidence)},
            )
        else:
            log_event(
                _log,
                logging.WARNING,
                "job.completed_unverified",
                job_id=job_id,
                attempt=attempt,
                worker_status=outcome.status,
                missing=[k for k in REQUIRED_EVIDENCE_KEYS if not (outcome.evidence or {}).get(k)],
            )
            self.store.update_job(job_id, state=JobState.COMPLETED_UNVERIFIED)
            self.store.record_event(
                "job_completed_unverified",
                {"job_id": job_id, "attempt": attempt,
                 "reason": "missing_or_incomplete_evidence",
                 "evidence": _bounded_evidence(outcome.evidence)},
            )
        updated = self.store.get_job(job_id)
        assert updated is not None
        return DispatchReceipt(
            job_id=job_id, attempt=attempt, final_state=updated.state
        )

    @staticmethod
    def _evidence_satisfies(outcome: WorkerOutcome) -> bool:
        ev = outcome.evidence or {}
        return all(isinstance(ev.get(k), str) and ev.get(k).strip() for k in REQUIRED_EVIDENCE_KEYS)

    # ------------------------------------------------------------------
    # reconciliation - human-only exit from interrupted/unknown
    # ------------------------------------------------------------------

    def reconcile(
        self,
        job_id: str,
        final_state: JobState,
        principal: Principal,
        note: str,
    ) -> Job:
        if principal is not Principal.HUMAN:
            raise PermissionError("only a human principal may reconcile an unknown outcome")
        if final_state not in (
            JobState.COMPLETED_VERIFIED,
            JobState.COMPLETED_UNVERIFIED,
            JobState.FAILED,
        ):
            raise ValueError(f"invalid reconcile target state: {final_state}")
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.state is not JobState.INTERRUPTED_UNKNOWN:
            raise ValueError(f"job is not interrupted/unknown (state={job.state.value})")
        self.store.update_job(job_id, state=final_state)
        self.store.record_event(
            "reconciled", {"job_id": job_id, "final_state": final_state.value, "note": note}
        )
        result = self.store.get_job(job_id)
        assert result is not None
        return result

    # ------------------------------------------------------------------
    # knowledge - revisioned, conflict-checked
    # ------------------------------------------------------------------

    def create_knowledge_doc(self, doc_id: str, title: str, content: str) -> None:
        self.store.create_knowledge_doc(doc_id, title, content)
        self.store.record_event("knowledge_created", {"doc_id": doc_id})

    def apply_knowledge_edit(
        self, doc_id: str, base_revision: int, new_content: str
    ) -> int:
        doc = self.store.get_knowledge_doc(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        if doc["revision"] != base_revision:
            self.store.record_event(
                "knowledge_conflict",
                {"doc_id": doc_id, "base_revision": base_revision, "current": doc["revision"]},
            )
            raise ConflictError(
                f"stale revision: edit based on {base_revision}, current is {doc['revision']}"
            )
        new_rev = doc["revision"] + 1
        self.store.update_knowledge_doc(doc_id, new_rev, new_content)
        self.store.record_event(
            "knowledge_updated", {"doc_id": doc_id, "revision": new_rev}
        )
        return new_rev
