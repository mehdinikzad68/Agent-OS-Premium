# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

# -*- coding: utf-8 -*-
"""Phase 2 integration: request → decide → dispatch through the gate.

These tests verify the full approval lifecycle works end-to-end:
  - request_approval creates an approval in REQUESTED state
  - decide(GRANTED) from HUMAN passes the syscall gate
  - decide(GRANTED) from non-HUMAN is refused by the syscall gate
  - decide(GRANTED) on an expired approval is refused
  - after grant, dispatch succeeds
"""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from agent_os.adapters.fake import FakeExecutor
from agent_os.models import (
    ApprovalDecision,
    JobState,
    Principal,
    utc_now,
)
from agent_os.service import ControlService

PLANNER = Principal.PLANNER
HUMAN = Principal.HUMAN


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="phase2-int-"))
        self.svc = ControlService(self.tmp / "s.db")
        self.addCleanup(self.svc.close)
        self.mission = self.svc.create_mission("P2I")
        self.src = self.tmp / "src"
        self.src.mkdir()
        self.adapter = FakeExecutor()

    def _job(self, command=None, actions=("run_tests",)):
        return self.svc.record_proposal(
            self.mission.id, "t", "subprocess-executor", (str(self.src),),
            actions, PLANNER, command=command,
        )


class FullLifecycleTest(_Base):
    def test_grant_then_dispatch_succeeds(self):
        """request → decide(GRANTED) → dispatch: the happy path."""
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        self.assertEqual(appr.decision, ApprovalDecision.REQUESTED)

        self.svc.decide(appr.id, ApprovalDecision.GRANTED, HUMAN)
        updated = self.svc.store.get_approval(appr.id)
        self.assertEqual(updated.decision, ApprovalDecision.GRANTED)

        receipt = self.svc.dispatch(job.id, self.adapter)
        self.assertFalse(receipt.duplicated)
        self.assertEqual(len(self.adapter.invocations), 1)
        self.assertEqual(self.svc.store.get_job(job.id).state, JobState.COMPLETED_VERIFIED)

    def test_deny_then_dispatch_refused(self):
        """request → decide(DENIED) → dispatch: dispatch must fail."""
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)

        self.svc.decide(appr.id, ApprovalDecision.DENIED, HUMAN)
        updated = self.svc.store.get_approval(appr.id)
        self.assertEqual(updated.decision, ApprovalDecision.DENIED)

        from agent_os.service import DispatchRefused
        with self.assertRaises(DispatchRefused):
            self.svc.dispatch(job.id, self.adapter)

    def test_non_human_decision_refused(self):
        """decide(GRANTED) from PLANNER must raise PermissionError."""
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)

        with self.assertRaises(PermissionError):
            self.svc.decide(appr.id, ApprovalDecision.GRANTED, PLANNER)

        # Approval must remain REQUESTED
        updated = self.svc.store.get_approval(appr.id)
        self.assertEqual(updated.decision, ApprovalDecision.REQUESTED)

    def test_expired_approval_refused(self):
        """decide(GRANTED) on an expired approval must raise PermissionError."""
        job = self._job(["python", "-c", "print(1)"])
        past = utc_now() - timedelta(hours=1)
        appr = self.svc.request_approval(job.id, expires_at=past)

        with self.assertRaises(PermissionError):
            self.svc.decide(appr.id, ApprovalDecision.GRANTED, HUMAN)

    def test_missing_approval_raises_keyerror(self):
        """decide on a non-existent approval must raise KeyError."""
        with self.assertRaises(KeyError):
            self.svc.decide("nonexistent", ApprovalDecision.GRANTED, HUMAN)


if __name__ == "__main__":
    unittest.main()
