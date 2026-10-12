# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

# -*- coding: utf-8 -*-
"""Phase 2: approval decisions as first-class syscalls.

These tests pin the approval syscall gate:
  - approve and deny are known actions
  - only HUMAN may decide
  - approval must exist and be in REQUESTED state
  - approval must not be expired
  - syscall crash = fail-closed
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from agent_os.models import (
    Approval,
    ApprovalDecision,
    ApprovalScope,
    Job,
    JobState,
    Principal,
    encode_command,
    utc_now,
)
from agent_os.policy import validate_approval_decision
from agent_os.service import ControlService
from agent_os import syscall as sc

PLANNER = Principal.PLANNER
HUMAN = Principal.HUMAN
WORKER = Principal.WORKER


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="phase2-"))
        self.svc = ControlService(self.tmp / "s.db")
        self.addCleanup(self.svc.close)
        self.mission = self.svc.create_mission("P2")
        self.src = self.tmp / "src"
        self.src.mkdir()

    def _job(self, command=None, actions=("run_tests",)):
        return self.svc.record_proposal(
            self.mission.id, "t", "subprocess-executor", (str(self.src),),
            actions, PLANNER, command=command,
        )


class ApproveDenyAreKnownActionsTest(_Base):
    def test_approve_is_known(self):
        self.assertIn("approve", sc.KNOWN_ACTIONS)

    def test_deny_is_known(self):
        self.assertIn("deny", sc.KNOWN_ACTIONS)

    def test_dispatch_is_still_known(self):
        self.assertIn("dispatch", sc.KNOWN_ACTIONS)


class OnlyHumanMayDecideTest(_Base):
    def test_planner_cannot_approve(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        reason = validate_approval_decision(
            appr, PLANNER.value, "approve", utc_now()
        )
        self.assertIsNotNone(reason)
        self.assertIn("not_human", reason)

    def test_worker_cannot_approve(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        reason = validate_approval_decision(
            appr, WORKER.value, "approve", utc_now()
        )
        self.assertIsNotNone(reason)
        self.assertIn("not_human", reason)

    def test_human_can_approve(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        reason = validate_approval_decision(
            appr, HUMAN.value, "approve", utc_now()
        )
        self.assertIsNone(reason)

    def test_human_can_deny(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        reason = validate_approval_decision(
            appr, HUMAN.value, "deny", utc_now()
        )
        self.assertIsNone(reason)


class ApprovalStateTest(_Base):
    def test_already_granted_approval_cannot_be_approved_again(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        self.svc.decide(appr.id, ApprovalDecision.GRANTED, HUMAN)
        updated = self.svc.store.get_approval(appr.id)
        reason = validate_approval_decision(
            updated, HUMAN.value, "approve", utc_now()
        )
        self.assertIsNotNone(reason)
        self.assertIn("not_requested", reason)

    def test_already_denied_approval_cannot_be_approved(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        self.svc.decide(appr.id, ApprovalDecision.DENIED, HUMAN)
        updated = self.svc.store.get_approval(appr.id)
        reason = validate_approval_decision(
            updated, HUMAN.value, "approve", utc_now()
        )
        self.assertIsNotNone(reason)
        self.assertIn("not_requested", reason)


class ApprovalExpiryTest(_Base):
    def test_expired_approval_cannot_be_approved(self):
        job = self._job(["python", "-c", "print(1)"])
        past = utc_now() - timedelta(hours=1)
        appr = self.svc.request_approval(job.id, expires_at=past)
        reason = validate_approval_decision(
            appr, HUMAN.value, "approve", utc_now()
        )
        self.assertIsNotNone(reason)
        self.assertIn("expired", reason)

    def test_not_yet_expired_approval_can_be_approved(self):
        job = self._job(["python", "-c", "print(1)"])
        future = utc_now() + timedelta(hours=1)
        appr = self.svc.request_approval(job.id, expires_at=future)
        reason = validate_approval_decision(
            appr, HUMAN.value, "approve", utc_now()
        )
        self.assertIsNone(reason)


class MissingApprovalTest(_Base):
    def test_missing_approval_is_denied(self):
        reason = validate_approval_decision(
            None, HUMAN.value, "approve", utc_now()
        )
        self.assertIsNotNone(reason)
        self.assertIn("not_found", reason)


class SyscallApprovalPathTest(_Base):
    """The syscall gate itself routes approve/deny correctly."""

    def test_syscall_approve_allowed_for_human(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        verdict = sc.syscall(
            self.svc,
            sc.SyscallRequest(
                agent_id=HUMAN.value,
                action="approve",
                job_id=job.id,
                args={"approval_id": appr.id},
            ),
        )
        self.assertTrue(verdict.allowed)

    def test_syscall_approve_denied_for_planner(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        verdict = sc.syscall(
            self.svc,
            sc.SyscallRequest(
                agent_id=PLANNER.value,
                action="approve",
                job_id=job.id,
                args={"approval_id": appr.id},
            ),
        )
        self.assertFalse(verdict.allowed)

    def test_syscall_deny_allowed_for_human(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        verdict = sc.syscall(
            self.svc,
            sc.SyscallRequest(
                agent_id=HUMAN.value,
                action="deny",
                job_id=job.id,
                args={"approval_id": appr.id},
            ),
        )
        self.assertTrue(verdict.allowed)

    def test_syscall_unknown_approval_action_denied(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        verdict = sc.syscall(
            self.svc,
            sc.SyscallRequest(
                agent_id=HUMAN.value,
                action="revoke",
                job_id=job.id,
                args={"approval_id": appr.id},
            ),
        )
        self.assertFalse(verdict.allowed)

    def test_syscall_approval_crash_fail_closed(self):
        """If policy raises, the verdict is DENY (fail-closed)."""
        import unittest.mock as mock
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        # Mock the policy to raise an exception
        with mock.patch(
            'agent_os.syscall.validate_approval_decision',
            side_effect=RuntimeError("simulated policy crash"),
        ):
            verdict = sc.syscall(
                self.svc,
                sc.SyscallRequest(
                    agent_id=HUMAN.value,
                    action="approve",
                    job_id=job.id,
                    args={"approval_id": appr.id},
                ),
            )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "policy_error_fail_closed")


if __name__ == "__main__":
    unittest.main()
