"""Enforcement and durability tests for the control-service skeleton.

Each test maps to an acceptance criterion of AGENT-OS-HANDOFF.md
section 8 / architecture brief section 7:

  A1 restart preserves mission/approval/event state
  A2 expired approval or unapproved destination refused BEFORE dispatch
  A3 planner cannot self-approve or enlarge the tool inventory
  A4 missing test report is never verified completion
  A5 lost worker stays interrupted/unknown until human reconciliation
  A6 replayed events / duplicate dispatch perform no duplicate action
  A7 knowledge edit on a stale revision raises a conflict

Proof that denial happens BEFORE dispatch in every A2/A3 test:
adapter.invocations must be empty.
"""

from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os.adapters.fake import FakeExecutor
from agent_os.models import (
    ApprovalDecision,
    ApprovalScope,
    ConflictError,
    DispatchRefused,
    JobState,
    Principal,
)
from agent_os.service import ControlService

T0 = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(hours=2)

HUMAN = Principal.HUMAN
PLANNER = Principal.PLANNER
WORKER = Principal.WORKER

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class ControlServiceTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db_path = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db_path.exists():
            self.db_path.unlink()
        self.svc = ControlService(self.db_path)

    def tearDown(self):
        self.svc.close()
        shutil.rmtree(TMP, ignore_errors=True)

    # -- shared flow ----------------------------------------------------

    def _approved_job(self, adapter_name: str = "fake-executor", **kwargs):
        """mission -> planner proposal -> approval request -> human grant."""
        mission = self.svc.create_mission("fix failing test", now=T0)
        self.svc.activate_mission(mission.id)
        job = self.svc.record_proposal(
            mission_id=mission.id,
            title="fix test_parser.py::test_roundtrip",
            executor=adapter_name,
            workspace_paths=("workspaces/mission-1/",),
            actions=("read_file", "write_file", "run_tests"),
            proposed_by=PLANNER,
            now=T0,
        )
        approval = self.svc.request_approval(
            job.id, expires_at=kwargs.pop("expires_at", T2), now=T0
        )
        self.svc.decide(approval.id, ApprovalDecision.GRANTED, HUMAN, now=T0)
        return mission, job, approval

    # -- A1 --------------------------------------------------------------

    def test_a1_restart_preserves_all_state(self):
        """Restarting the service preserves mission state, approval
        decisions and event history."""
        mission, job, _ = self._approved_job()
        adapter = FakeExecutor(behavior="success")
        receipt = self.svc.dispatch(job.id, adapter, now=T1)
        self.assertIs(receipt.final_state, JobState.COMPLETED_VERIFIED)
        events_before = self.svc.store.list_events()
        self.svc.close()

        svc2 = ControlService(self.db_path)  # "restart"
        try:
            m2 = svc2.store.get_mission(mission.id)
            self.assertEqual(m2.state.value, "active")
            j2 = svc2.store.get_job(job.id)
            self.assertIs(j2.state, JobState.COMPLETED_VERIFIED)
            self.assertEqual(j2.attempt_no, 1)
            a2 = svc2.store.latest_approval_for_job(job.id)
            self.assertIs(a2.decision, ApprovalDecision.GRANTED)
            self.assertIs(a2.decided_by, HUMAN)
            events_after = svc2.store.list_events()
            self.assertEqual(
                [e["seq"] for e in events_before], [e["seq"] for e in events_after]
            )
            self.assertEqual(events_after, events_before)
        finally:
            svc2.close()

    # -- A2 --------------------------------------------------------------

    def test_a2_expired_approval_refused_before_dispatch(self):
        """A stale/expired approval is refused before the executor runs."""
        mission, job, _ = self._approved_job(expires_at=T0 + timedelta(minutes=30))
        adapter = FakeExecutor(behavior="success")
        with self.assertRaises(DispatchRefused) as ctx:
            self.svc.dispatch(job.id, adapter, now=T1)  # T1 > expiry
        self.assertEqual(ctx.exception.reason, "approval_expired")
        self.assertEqual(adapter.invocations, [])  # denied BEFORE dispatch
        j = self.svc.store.get_job(job.id)
        self.assertEqual(j.state, JobState.APPROVED)  # not dispatched
        denied = [e for e in self.svc.store.list_events() if e["kind"] == "dispatch_denied"]
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0]["payload"]["reason"], "approval_expired")

    def test_a2_unapproved_destination_refused_before_dispatch(self):
        """A dispatch to a destination the human never approved is refused
        before the executor runs."""
        mission = self.svc.create_mission("m", now=T0)
        self.svc.activate_mission(mission.id)
        job = self.svc.record_proposal(
            mission.id, "t", "unapproved-executor", ("w/",),
            ("read_file", "run_tests"), PLANNER, now=T0
        )
        # the human's grant is scoped to a DIFFERENT destination
        approval = self.svc.request_approval(
            job.id, expires_at=T2, now=T0,
            scope=ApprovalScope("fake-executor", ("w/",), ("read_file", "run_tests")),
        )
        self.svc.decide(approval.id, ApprovalDecision.GRANTED, HUMAN, now=T0)
        adapter = FakeExecutor(behavior="success")
        with self.assertRaises(DispatchRefused) as ctx:
            self.svc.dispatch(job.id, adapter, now=T1)
        self.assertEqual(ctx.exception.reason, "destination_not_approved:unapproved-executor")
        self.assertEqual(adapter.invocations, [])  # denied BEFORE dispatch
        self.assertEqual(self.svc.store.get_job(job.id).state, JobState.APPROVED)

    def test_a2_manifest_change_after_grant_requires_new_decision(self):
        """Editing the job after the grant invalidates it: changed package/
        scope/parameters require another human decision."""
        mission, job, _ = self._approved_job()
        self.svc.amend_job(job.id, workspace_paths=("workspaces/mission-1/", "C:/other/"))
        adapter = FakeExecutor(behavior="success")
        with self.assertRaises(DispatchRefused) as ctx:
            self.svc.dispatch(job.id, adapter, now=T1)
        self.assertTrue(ctx.exception.reason.startswith(("manifest_changed", "path_not_in_scope")))
        self.assertEqual(adapter.invocations, [])

    # -- A3 --------------------------------------------------------------

    def test_a3_no_self_approval_planner_or_worker(self):
        """A planner or worker principal cannot approve anything; approval
        denied attempts are recorded and change no state."""
        mission = self.svc.create_mission("m", now=T0)
        job = self.svc.record_proposal(
            mission.id, "t", "fake-executor", ("w/",), ("read_file",), PLANNER, now=T0
        )
        approval = self.svc.request_approval(job.id, expires_at=T2, now=T0)
        for impostor in (PLANNER, WORKER):
            with self.assertRaises(PermissionError):
                self.svc.decide(approval.id, ApprovalDecision.GRANTED, impostor, now=T0)
        j = self.svc.store.get_job(job.id)
        self.assertEqual(j.state, JobState.AWAITING_APPROVAL)  # unchanged
        rejected = [e for e in self.svc.store.list_events()
                    if e["kind"] == "approval_decision_rejected"]
        self.assertEqual(len(rejected), 2)
        # the human CAN decide
        self.svc.decide(approval.id, ApprovalDecision.GRANTED, HUMAN, now=T0)
        self.assertIs(self.svc.store.get_job(job.id).state, JobState.APPROVED)

    def test_a3_tool_inventory_cannot_be_enlarged(self):
        """A proposal asking for tools outside the adapter's fixed inventory
        is refused at dispatch even when the human approved the actions."""
        mission = self.svc.create_mission("m", now=T0)
        job = self.svc.record_proposal(
            mission.id, "t", "fake-executor", ("w/",),
            ("read_file", "format_disk"), PLANNER, now=T0
        )
        approval = self.svc.request_approval(
            job.id,
            expires_at=T2,
            now=T0,
            scope=ApprovalScope("fake-executor", ("w/",), ("read_file", "format_disk")),
        )
        self.svc.decide(approval.id, ApprovalDecision.GRANTED, HUMAN, now=T0)
        adapter = FakeExecutor(behavior="success")
        with self.assertRaises(DispatchRefused) as ctx:
            self.svc.dispatch(job.id, adapter, now=T1)
        self.assertTrue(ctx.exception.reason.startswith("actions_not_supported"))
        self.assertNotIn("read_file", ctx.exception.reason)
        self.assertIn("format_disk", ctx.exception.reason)
        self.assertEqual(adapter.invocations, [])

    # -- A4 --------------------------------------------------------------

    def test_a4_missing_test_report_is_not_verified_completion(self):
        """A worker claiming completion without a test report cannot be
        displayed as verified completion."""
        mission, job, _ = self._approved_job()
        adapter = FakeExecutor(behavior="missing_evidence")
        receipt = self.svc.dispatch(job.id, adapter, now=T1)
        self.assertIs(receipt.final_state, JobState.COMPLETED_UNVERIFIED)
        j = self.svc.store.get_job(job.id)
        self.assertIs(j.state, JobState.COMPLETED_UNVERIFIED)
        self.assertIsNot(j.state, JobState.COMPLETED_VERIFIED)
        events = [e["kind"] for e in self.svc.store.list_events()]
        self.assertIn("job_completed_unverified", events)
        self.assertNotIn("job_completed_verified", events)

    # -- A5 --------------------------------------------------------------

    def test_a5_worker_loss_stays_interrupted_unknown(self):
        """A disconnected worker becomes interrupted/unknown: not successful,
        not auto-rerun, and only a human can reconcile it."""
        mission, job, _ = self._approved_job()
        adapter = FakeExecutor(behavior="crash_after_effect")
        receipt = self.svc.dispatch(job.id, adapter, now=T1)
        self.assertIs(receipt.final_state, JobState.INTERRUPTED_UNKNOWN)
        j = self.svc.store.get_job(job.id)
        self.assertIs(j.state, JobState.INTERRUPTED_UNKNOWN)
        self.assertEqual(j.attempt_no, 1)  # the attempt was persisted

        # automatic re-dispatch is refused
        fresh_adapter = FakeExecutor(behavior="success")
        with self.assertRaises(DispatchRefused) as ctx:
            self.svc.dispatch(job.id, fresh_adapter, now=T1)
        self.assertEqual(ctx.exception.reason, "interrupted_unknown_requires_human_reconcile")
        self.assertEqual(fresh_adapter.invocations, [])

        # non-human reconciliation is refused
        for impostor in (PLANNER, WORKER):
            with self.assertRaises(PermissionError):
                self.svc.reconcile(job.id, JobState.FAILED, impostor, "auto")

        # human reconciliation works and is audited
        self.svc.reconcile(job.id, JobState.FAILED, HUMAN, "checked workspace: no changes")
        self.assertIs(self.svc.store.get_job(job.id).state, JobState.FAILED)
        events = [e["kind"] for e in self.svc.store.list_events()]
        self.assertIn("worker_lost", events)
        self.assertIn("reconciled", events)

    # -- A6 --------------------------------------------------------------

    def test_a6_duplicate_dispatch_and_event_replay_no_duplicate_action(self):
        """Replayed UI events do not duplicate actions; a repeated dispatch
        request reuses the same attempt instead of executing again."""
        mission, job, _ = self._approved_job()
        adapter = FakeExecutor(behavior="success")

        r1 = self.svc.dispatch(job.id, adapter, now=T1)
        self.assertFalse(r1.duplicated)
        self.assertEqual(r1.attempt, 1)

        r2 = self.svc.dispatch(job.id, adapter, now=T1)  # duplicate request
        self.assertTrue(r2.duplicated)
        self.assertEqual(r2.attempt, 1)
        self.assertEqual(len(adapter.invocations), 1)  # executed exactly once

        # event with the same dedup_key is ignored on replay
        inserted = self.svc.store.record_event(
            "dispatched", {"job_id": job.id, "attempt": 1}, dedup_key=f"dispatch:{job.id}:1"
        )
        self.assertFalse(inserted)
        dispatched_events = [e for e in self.svc.store.list_events() if e["kind"] == "dispatched"]
        self.assertEqual(len(dispatched_events), 1)

    # -- A7 --------------------------------------------------------------

    def test_a7_stale_knowledge_revision_conflicts(self):
        """A canonical knowledge edit against a stale revision raises a conflict."""
        self.svc.create_knowledge_doc("decisions", "Architecture decisions", "v0 content")
        rev1 = self.svc.apply_knowledge_edit("decisions", 0, "v1 content")
        self.assertEqual(rev1, 1)
        with self.assertRaises(ConflictError):
            self.svc.apply_knowledge_edit("decisions", 0, "stale edit based on rev 0")
        doc = self.svc.store.get_knowledge_doc("decisions")
        self.assertEqual(doc["revision"], 1)
        self.assertEqual(doc["content"], "v1 content")  # stale edit did not apply
        conflicts = [e for e in self.svc.store.list_events() if e["kind"] == "knowledge_conflict"]
        self.assertEqual(len(conflicts), 1)


if __name__ == "__main__":
    unittest.main()
