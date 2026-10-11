# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

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
from . import discovery
from .logging_setup import get_logger, log_event, redact
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
    ApprovalAction,
    ApprovalDecision,
    ApprovalScope,
    ConflictError,
    DispatchReceipt,
    DispatchRefused,
    Job,
    JobState,
    Mission,
    MissionState,
    NodeActionType,
    Principal,
    Project,
    ProjectRejected,
    Tool,
    ToolRejected,
    WorkerLostError,
    WorkerOutcome,
    WorkflowExecution,
    WorkflowNode,
    WorkflowNodeState,
    WorkflowTemplate,
    encode_command,
    iso,
    utc_now,
)
from .graphics import Graphic, GraphicKind, GraphicState, render_graphic
from .policy import validate_dispatch
from .store import Store, _new_id

#: Evidence keys that must be non-empty for a job to count as VERIFIED.
REQUIRED_EVIDENCE_KEYS = ("diff", "test_report")

#: Evidence strings longer than this are truncated when persisted into the
#: append-only event log (keeps events bounded; the run itself is already
#: bounded by the executor's own capture limits).
EVENT_EVIDENCE_STRING_LIMIT = 16_384


def _bounded_evidence(evidence: dict | None) -> dict:
    """Bound, then redact, every string before it reaches the event log.

    M2 (B2, review 2026-10-05): evidence is raw executor stdout, so it can
    carry whatever the command printed - tokens included (F5 demonstrated
    `password=hunter2` arriving at /evidence). Redaction runs BEFORE
    truncation so a cut cannot leave half a secret behind.
    """
    out: dict = {}
    for k, v in (evidence or {}).items():
        if isinstance(v, str):
            v = redact(v)
            if len(v) > EVENT_EVIDENCE_STRING_LIMIT:
                v = v[:EVENT_EVIDENCE_STRING_LIMIT] + "\n...[truncated]"
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
    # external event ingestion (Phase 4, observation only)
    # ------------------------------------------------------------------

    def ingest_external(
        self, source_path: str, cursor: int = 0, limit: int = 500
    ) -> dict:
        """Read real activity from an external source into the event log.

        Observation only: this reads what another runtime already recorded and
        labels each row with where it came from. It creates nothing, executes
        nothing, and blocks nothing. Because the source records tool RESULTS,
        an ingested event can say what happened and must never be worded as
        something that was prevented or intercepted - that is Phase 5.

        The dedup_key is the source's own row id, so a re-read of the same
        range is a no-op rather than a second copy. That is what makes a
        reconnect safe: the cursor may go backwards and the log will not grow.

        Returns a summary that distinguishes three outcomes the UI must not
        conflate: events were added, the source is readable with nothing new,
        or the source could not be read at all.
        """
        from .adapters.hermes_ingest import (
            SourceUnavailable,
            StateReader,
            assert_source_allowed,
        )

        # M1 (B2): the source is caller-supplied; without this the route is
        # a token-gated arbitrary local SQLite read (git_repo_root leaks
        # real paths). Outside the allowed roots -> PermissionError -> 403.
        assert_source_allowed(source_path)
        reader = StateReader(source_path)
        try:
            probe = reader.probe()
            events, new_cursor = reader.read_since(cursor, limit)
        except SourceUnavailable as e:
            # Not an empty timeline. The UI must be able to say "cannot see".
            return {
                "status": "unavailable",
                "reason": str(e),
                "added": 0,
                "cursor": cursor,
                "skipped": 0,
            }

        added = 0
        skipped = 0
        for ev in events:
            payload = {
                "source": ev.source,
                "tool_name": ev.tool_name,
                "tool_call_id": ev.tool_call_id,
                "source_row_id": ev.row_id,
                "source_timestamp": ev.timestamp,
                "session_id": ev.session_id,
                "model": ev.model,
                "repo_root": ev.repo_root,
                "notes": list(ev.notes),
                "observed_only": True,
            }
            # dedup on the source's own id: a replay is a no-op
            if self.store.record_event(
                "external.tool_call", payload,
                dedup_key=f"hermes:{ev.row_id}",
            ):
                added += 1
            else:
                skipped += 1

        return {
            "status": "ok",
            "reason": None,
            "added": added,
            "cursor": new_cursor,
            "skipped": skipped,
            "source": {"path": source_path, **probe},
        }

    def list_external_events(self) -> list[dict]:
        """Ingested events only, newest first, for the timeline panel."""
        return [e for e in self.store.list_events()
                if e["kind"] == "external.tool_call"]

    # ------------------------------------------------------------------
    # missions
    # ------------------------------------------------------------------

    # -- projects -------------------------------------------------------

    def list_projects(self) -> list[Project]:
        return self.store.list_projects()

    def remove_project(self, project_id: str) -> bool:
        """Forget a project. Returns False when the id was unknown."""
        removed = self.store.delete_project(project_id)
        if removed:
            self.store.record_event("project_removed", {"project_id": project_id})
            log_event(_log, logging.INFO, "project.removed", project_id=project_id)
        return removed

    # -- tools (Phase 3) -------------------------------------------------

    def register_tool(
        self,
        name: str,
        environment: str,
        path: Optional[str] = None,
        version: Optional[str] = None,
        confidence: str = "unknown",
    ) -> Tool:
        """Record a tool the owner has reviewed.

        This records a fact and grants nothing. `grants_execution` is False on
        every row and nothing in the executor reads this table, so a tool the
        owner approves here is still not something any job may run.

        The environment is validated against the same list discovery uses.
        Accepting an arbitrary one would let a caller file a row claiming
        coverage of a platform this service has no test evidence for - and a
        registry that can hold such a claim is worse than one that cannot.
        """
        if environment not in discovery.SUPPORTED_ENVIRONMENTS:
            log_event(_log, logging.WARNING, "tool.rejected",
                      reason="environment_unsupported",
                      environment=str(environment)[:40],
                      tool_name=str(name)[:60])
            raise ToolRejected(
                "environment_unsupported",
                f"environment {environment!r} has no test evidence in this "
                f"service; supported: {', '.join(discovery.SUPPORTED_ENVIRONMENTS)}",
            )
        tool = self.store.create_tool(
            name=name, environment=environment, path=path,
            version=version, confidence=confidence,
        )
        log_event(_log, logging.INFO, "tool.registered",
                  tool_name=tool.name, environment=tool.environment,
                  confidence=tool.confidence, grants_execution=False)
        return tool

    def list_tools(self) -> list[Tool]:
        return self.store.list_tools()

    def remove_tool(self, tool_id: str) -> bool:
        """Remove a registry row. Removing grants nothing either - it only
        forgets a record, and the tool on disk is untouched."""
        removed = self.store.delete_tool(tool_id)
        log_event(_log, logging.INFO, "tool.removed" if removed else
                  "tool.remove_missed", tool_id=str(tool_id)[:60])
        return removed

    def register_project(
            self,
            name: str,
            environment: str,
            root: str,
    ) -> Project:
        """Validate a project root and record it. Read-only against the disk.

        Two gates, in this order. The lexical one is pure and cheap; the disk
        one is what sees a symlink escaping the scope. Both must pass.

        The allowed scope is NOT a parameter. It used to be, and the HTTP handler
        never passed it, so no caller could supply one - measured across all nine
        call sites. A parameter that no caller can reach reads as a control the
        operator can turn, and costs the next reader an experiment to discover
        otherwise. More importantly, letting a client name its own boundary is the
        wrong direction: the scope is a property of the deployment, configured
        through AGENT_OS_PROJECT_SCOPE, and a caller asking to widen it is asking
        to remove the check that is protecting it.

        So the scope comes from configuration or not at all, and a project whose
        root falls outside it is refused.
        """
        scope = project_scope()
        if scope is None:
            log_event(_log, logging.WARNING, "project.rejected",
                      reason=REASON_SCOPE_UNSET, root=root[:200])
            raise ProjectRejected(
                REASON_SCOPE_UNSET,
                f"set {PROJECT_SCOPE_ENV} to the directory projects may live in",
            )

        lexical = check_project_root(root, scope, environment)
        if not lexical.ok:
            log_event(_log, logging.WARNING, "project.rejected",
                      reason=lexical.reason, root=root[:200])
            raise ProjectRejected(lexical.reason, f"refused {root!r}: {lexical.reason}")

        disk = inspect_root(root, scope, environment)
        if not disk.ok:
            log_event(_log, logging.WARNING, "project.rejected",
                      reason=disk.reason, root=root[:200])
            raise ProjectRejected(disk.reason, f"refused {root!r}: {disk.reason}")

        project = self.store.create_project(
            name=name,
            environment=environment,
            root=root,
            canonical_root=disk.canonical,
            is_symlink=disk.is_symlink,
        )
        if project is None:
            log_event(_log, logging.WARNING, "project.rejected",
                      reason="duplicate", root=disk.canonical)
            raise ProjectRejected(
                "duplicate", f"{environment}:{disk.canonical} is already registered"
            )
        self.store.record_event(
            "project_registered",
            {"project_id": project.id, "name": name, "root": disk.canonical,
             "is_symlink": disk.is_symlink},
        )
        log_event(
            _log, logging.INFO, "project.registered",
            project_id=project.id, project_name=name[:120], root=disk.canonical,
            is_symlink=disk.is_symlink,
        )
        return project

    def create_mission(self, title: str, now: Optional[datetime] = None) -> Mission:
        now = now or utc_now()
        mission = self.store.create_mission(title, now)
        self.store.record_event("mission_created", {"mission_id": mission.id, "title": title})
        log_event(_log, logging.INFO, "mission.created", mission_id=mission.id, title=title[:120])
        return mission

    def activate_mission(self, mission_id: str) -> Mission:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            # Checked BEFORE any write. The previous order updated the state,
            # recorded the event and logged, then asserted - so activating a
            # mission that does not exist still wrote an event to the feed, and
            # the bare `assert` raised AssertionError (a 500) instead of the
            # 404 the caller deserves. An assert also disappears under -O.
            raise KeyError(f"mission not found: {mission_id!r}")
        self.store.update_mission_state(mission_id, MissionState.ACTIVE)
        self.store.record_event("mission_activated", {"mission_id": mission_id})
        log_event(_log, logging.INFO, "mission.activated", mission_id=mission_id)
        return self.store.get_mission(mission_id)

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
        command: Optional[list] = None,
    ) -> Job:
        if proposed_by not in (Principal.PLANNER, Principal.HUMAN):
            raise PermissionError("proposals come from planner or human only")
        if self.store.get_mission(mission_id) is None:
            # B3 (review 2026-10-05): application-level referential check.
            # The schema declares no FOREIGN KEY (the pragma in store.py is
            # otherwise dead), so without this a job could reference a
            # mission that never existed. KeyError -> HTTP 404.
            raise KeyError(mission_id)
        now = now or utc_now()
        # Encode HERE, not at the HTTP edge. The HTTP layer validates the
        # shape, but record_proposal is also called directly (tests, CLI,
        # future adapters) and every one of those paths writes to the same TEXT
        # column. Encoding at the single write boundary means no caller can
        # put a list into sqlite and get a 500 from three frames down - which
        # is exactly defect F8.
        encoded = encode_command(command)
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
            command=encoded,
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
        command: Optional[list] = None,
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
        encoded = None
        if command is not None:
            # Same reason as record_proposal: this is a write boundary.
            encoded = encode_command(command)
            job.command = encoded
        job.manifest_hash = job.compute_manifest_hash()
        self.store.update_job(
            job_id, manifest_hash=job.manifest_hash, command=encoded
        )
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
        action: Optional[str] = None,
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
        # The command is the OPERATION, so it is never taken from a scope
        # argument - not even an internally-constructed one. It is copied from
        # the job, always, and any command the caller put in the scope is
        # discarded. Doing this here rather than only in the API layer means a
        # direct service caller cannot strip it either.
        #
        # Why this matters even though stripping is fail-closed (a scope with
        # no command authorizes no command, so dispatch is refused): the human
        # would be shown a scope with no command while the job has one, and
        # "the approval does not name the operation" is exactly the blindness
        # F1 is about. A grant must always describe what it authorizes.
        #
        # Phase 5: action binding. The action is copied from the job's first
        # action if not explicitly provided. This binds the approval to a
        # specific operation, not just a ceiling.
        if action is None:
            action = job.actions[0] if job.actions else None
        scope = ApprovalScope(
            executor=scope.executor,
            workspace_paths=scope.workspace_paths,
            actions=scope.actions,
            command=job.command,
            action=action,
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
        if self.store.get_approval(approval_id) is None:
            # A3 (B2): resolve BEFORE any write. The old order updated 0
            # rows silently and then hit `assert approval is not None` ->
            # a 500 (and the assert disappears under python -O).
            raise KeyError(approval_id)
        now = now or utc_now()
        self.store.update_approval_decision(approval_id, decision, iso(now), principal)
        approval = self.store.get_approval(approval_id)
        if approval is None:  # unreachable without a concurrent delete
            raise KeyError(approval_id)
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
        # This MUST stay ahead of the consumed-approval check below: a retry of
        # a finished dispatch is a replay, not an error. The action already ran
        # once (that is what single-use means); reporting 409 here would break
        # the documented A6 contract and e2e step 7.
        if job.state in (JobState.DISPATCHED, JobState.RUNNING) or job.state in (
            JobState.COMPLETED_VERIFIED, JobState.COMPLETED_UNVERIFIED, JobState.FAILED
        ):
            return DispatchReceipt(
                job_id=job_id, attempt=job.attempt_no, final_state=job.state, duplicated=True
            )

        # A2: policy validation BEFORE the executor is ever touched. A
        # consumed approval is refused here (policy check 9) - after A6, so an
        # idempotent replay is not mistaken for a fresh, unauthorised attempt.
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

        # Phase 5 + H1: spend the approval BEFORE any state is written and
        # before the executor runs. consume_approval() is an atomic
        # UPDATE ... WHERE consumed_at IS NULL, so it doubles as the
        # single-winner gate: of two threads that both passed
        # validate_dispatch over the same unspent approval
        # (ThreadingHTTPServer dispatches concurrently; the store's RLock
        # serializes each store CALL, not this check-then-act sequence),
        # exactly one receives True. The loser is refused here - before it
        # can touch the job's state or the audit trail - so one approval can
        # never run two executions, and the shared dedup key can never hide
        # a second run. Even if the executor crashes afterwards, the
        # approval is already spent: a crashed job stays
        # INTERRUPTED_UNKNOWN and cannot be re-dispatched with it.
        attempt = job.attempt_no + 1
        if approval is None or not self.store.consume_approval(approval.id, iso(now)):
            self.store.record_event(
                "dispatch_denied",
                {"job_id": job_id, "reason": "approval_already_consumed"},
            )
            log_event(
                _log,
                logging.WARNING,
                "dispatch.refused",
                job_id=job_id,
                reason="approval_already_consumed",
            )
            raise DispatchRefused("approval_already_consumed")

        self.store.record_event(
            "approval_consumed",
            {"approval_id": approval.id, "job_id": job_id, "attempt": attempt},
        )

        # Persist the dispatch intent BEFORE invoking the executor.
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
            if updated is None:
                raise RuntimeError(
                    f"job {job_id} vanished from the store on the "
                    "worker-lost path (no delete path exists)"
                )
            return DispatchReceipt(
                job_id=job_id, attempt=attempt, final_state=updated.state
            )
        except Exception:
            # A2-fix (B2): anything other than WorkerLostError leaving this
            # try means the executor could not do its work at all (sandbox
            # preparation, escaping-link scan, ...). Without this the job
            # stayed RUNNING forever: A6 then answered duplicated=True for
            # every retry and reconcile() refuses non-INTERRUPTED states, so
            # the job became unreachable. FAILED is the honest terminal
            # state; WorkerLostError stays the explicit "outcome unknown"
            # channel - an executor that may already have spawned work must
            # raise that instead.
            self.store.update_job(job_id, state=JobState.FAILED)
            self.store.record_event(
                "dispatch_failed",
                {"job_id": job_id, "attempt": attempt, "reason": "executor_error"},
            )
            log_event(
                _log,
                logging.ERROR,
                "dispatch.executor_error",
                exc_info=True,
                job_id=job_id,
                attempt=attempt,
            )
            raise

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
        if updated is None:
            raise RuntimeError(
                f"job {job_id} vanished from the store after dispatch "
                "(no delete path exists)"
            )
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
        if result is None:
            raise RuntimeError(
                f"job {job_id} vanished during reconcile (no delete path exists)"
            )
        return result

    # ------------------------------------------------------------------
    # configurable workflows (Phase 9)
    # ------------------------------------------------------------------

    def create_workflow_template(
        self,
        title: str,
        description: str,
        inputs_schema: dict,
        default_executor: str,
        nodes: list[dict],
        now=None,
    ) -> dict:
        """Create a workflow template with its node graph.

        Each node dict must have: id, action_type, metadata, depends_on.
        Returns the template dict with all nodes.
        """
        now = now or utc_now()
        template_id = _new_id("wf")
        created_at = iso(now)
        self.store.create_workflow_template(
            template_id=template_id,
            title=title,
            description=description,
            created_at=created_at,
            version=1,
            inputs_schema=inputs_schema,
            default_executor=default_executor,
        )
        for i, node in enumerate(nodes):
            self.store.insert_workflow_node(
                node_id=node["id"],
                workflow_id=template_id,
                action_type=node["action_type"],
                metadata=node.get("metadata", {}),
                depends_on=node.get("depends_on", []),
                seq=i,
            )
        return self.get_workflow_template(template_id)

    def get_workflow_template(self, template_id: str) -> Optional[dict]:
        template = self.store.get_workflow_template(template_id)
        if template is None:
            return None
        template["nodes"] = self.store.get_workflow_nodes(template_id)
        return template

    def list_workflow_templates(self) -> list[dict]:
        return self.store.list_workflow_templates()

    def execute_workflow(
        self,
        template_id: str,
        inputs: dict,
        now=None,
    ) -> dict:
        """Instantiate a workflow template as a running execution.

        Creates a WorkflowExecution + a new Mission, then fans out the
        root nodes (those with no dependencies) as job proposals.
        Returns the execution dict.
        """
        now = now or utc_now()
        template = self.store.get_workflow_template(template_id)
        if template is None:
            raise KeyError(f"workflow template not found: {template_id!r}")

        # Create the execution and its mission
        execution_id = _new_id("wfx")
        mission = self.create_mission(
            title=f"Workflow: {template['title']}", now=now
        )
        self.activate_mission(mission.id)
        self.store.create_workflow_execution(
            execution_id=execution_id,
            workflow_id=template_id,
            mission_id=mission.id,
            status="active",
            inputs=inputs,
            created_at=iso(now),
        )

        # Fan out root nodes as job proposals
        nodes = self.store.get_workflow_nodes(template_id)
        root_nodes = [n for n in nodes if not n.get("depends_on")]
        for node in root_nodes:
            self._propose_node_job(
                node=node,
                execution_id=execution_id,
                mission_id=mission.id,
                inputs=inputs,
                default_executor=template["default_executor"],
                now=now,
            )

        return self.get_workflow_execution(execution_id)

    def get_workflow_execution(self, execution_id: str) -> Optional[dict]:
        return self.store.get_workflow_execution(execution_id)

    def list_workflow_executions(self) -> list[dict]:
        return self.store.list_workflow_executions()

    def _propose_node_job(
        self,
        node: dict,
        execution_id: str,
        mission_id: str,
        inputs: dict,
        default_executor: str,
        now,
    ) -> Optional[Job]:
        """Create a job proposal for a single workflow node.

        Returns None if the node type does not map to a job (e.g.
        HUMAN_APPROVAL nodes are handled by the approval gate).
        """
        action_type = node.get("action_type", NodeActionType.EXECUTE_JOB.value)
        if action_type == NodeActionType.HUMAN_APPROVAL.value:
            return None
        if action_type == NodeActionType.CONDITIONAL_BRANCH.value:
            return None

        metadata = node.get("metadata", {})
        executor = metadata.get("executor", default_executor)
        actions = tuple(metadata.get("actions", ["run_command"]))
        workspace_paths = tuple(metadata.get("workspace_paths", []))
        command = metadata.get("command")

        # Resolve {{inputs.xxx}} placeholders in command
        if command and isinstance(command, list):
            resolved = []
            for part in command:
                if isinstance(part, str) and part.startswith("{{inputs.") and part.endswith("}}"):
                    key = part[9:-2]
                    if key in inputs:
                        resolved.append(str(inputs[key]))
                    # If key not in inputs, skip this part (don't add empty string)
                else:
                    resolved.append(part)
            command = resolved

        return self.record_proposal(
            mission_id=mission_id,
            title=f"[{execution_id[:8]}] {node['id']}",
            executor=executor,
            workspace_paths=workspace_paths,
            actions=actions,
            proposed_by=Principal.PLANNER,
            now=now,
            command=command,
        )

    # ------------------------------------------------------------------
    # simple graphics - تکرارهای گرافیکی بکر
    # ------------------------------------------------------------------

    def create_graphic(self, title: str, kind: str,
                       config: Optional[dict] = None, now=None) -> dict:
        # Validate kind is a known member (raises ValueError -> 400 at API).
        GraphicKind(kind)
        now = now or utc_now()
        gid = _new_id("gfx")
        return self.store.create_graphic(
            graphic_id=gid,
            title=title,
            kind=kind,
            config=config or {},
            created_at=iso(now),
            updated_at=iso(now),
        )

    def get_graphic(self, graphic_id: str) -> Optional[dict]:
        return self.store.get_graphic(graphic_id)

    def list_graphics(self, include_deleted: bool = False) -> list[dict]:
        return self.store.list_graphics(include_deleted=include_deleted)

    def update_graphic(self, graphic_id: str, patch: dict) -> dict:
        if not self.store.update_graphic_config(graphic_id, patch):
            raise KeyError(graphic_id)
        return self.store.get_graphic(graphic_id)

    def delete_graphic(self, graphic_id: str) -> bool:
        if not self.store.delete_graphic(graphic_id):
            raise KeyError(graphic_id)
        return True

    def render_graphic(self, graphic_id: str) -> str:
        row = self.store.get_graphic(graphic_id)
        if row is None:
            raise KeyError(graphic_id)
        if row["state"] == GraphicState.DELETED.value:
            raise ValueError("cannot render a deleted graphic")
        graphic = Graphic(
            id=row["id"], title=row["title"], kind=row["kind"],
            config=row["config"], state=row["state"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
        return render_graphic(graphic)

    def export_graphic_settings(self, graphic_id: str) -> dict:
        row = self.store.get_graphic(graphic_id)
        if row is None:
            raise KeyError(graphic_id)
        graphic = Graphic(
            id=row["id"], title=row["title"], kind=row["kind"],
            config=row["config"], state=row["state"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
        return graphic.export_settings()

    def import_graphic_settings(self, bundle: dict) -> dict:
        graphic = Graphic.from_export(bundle)
        return self.store.create_graphic(
            graphic_id=graphic.id,
            title=graphic.title,
            kind=graphic.kind,
            config=graphic.config,
            created_at=graphic.created_at,
            updated_at=graphic.updated_at,
        )

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
