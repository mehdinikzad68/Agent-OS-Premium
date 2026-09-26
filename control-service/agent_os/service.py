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

from datetime import datetime
from pathlib import Path
from typing import Optional

from .adapters.fake import FakeExecutor  # noqa: F401  (re-export for tests)
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


class ControlService:
    def __init__(self, db_path: str | Path):
        self.store = Store(db_path)

    def close(self) -> None:
        self.store.close()

    # ------------------------------------------------------------------
    # missions
    # ------------------------------------------------------------------

    def create_mission(self, title: str, now: Optional[datetime] = None) -> Mission:
        now = now or utc_now()
        mission = self.store.create_mission(title, now)
        self.store.record_event("mission_created", {"mission_id": mission.id, "title": title})
        return mission

    def activate_mission(self, mission_id: str) -> Mission:
        self.store.update_mission_state(mission_id, MissionState.ACTIVE)
        self.store.record_event("mission_activated", {"mission_id": mission_id})
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
        else:
            self.store.update_job(approval.job_id, state=JobState.PROPOSED)
            self.store.record_event(
                "approval_denied", {"approval_id": approval_id, "job_id": approval.job_id}
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
            raise DispatchRefused(denial)

        # A3: the adapter's tool inventory is fixed; proposals cannot enlarge it.
        unsupported = [a for a in job.actions if a not in adapter.allowed_actions]
        if unsupported:
            reason = "actions_not_supported_by_executor:" + ",".join(unsupported)
            self.store.record_event("dispatch_denied", {"job_id": job_id, "reason": reason})
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

        try:
            outcome: WorkerOutcome = adapter.run(job, attempt)
        except WorkerLostError:
            # A5: the worker may already have taken effect. Unknown, not failed,
            # not successful, and never automatically retried.
            self.store.update_job(job_id, state=JobState.INTERRUPTED_UNKNOWN)
            self.store.record_event(
                "worker_lost", {"job_id": job_id, "attempt": attempt}
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
            self.store.update_job(job_id, state=JobState.COMPLETED_VERIFIED)
            self.store.record_event(
                "job_completed_verified",
                {"job_id": job_id, "attempt": attempt,
                 "evidence": _bounded_evidence(outcome.evidence)},
            )
        else:
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
