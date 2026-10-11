# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Phase 1 — the syscall gate (kernel deny-by-default + fail-closed).

These tests pin the properties that make the gate a gate and not a library
call:

  1. DENY BY DEFAULT — an action the kernel does not know is refused.
  2. FAIL CLOSED     — if policy evaluation raises, the verdict is DENY.
  3. AUDITABLE       — every verdict, allowed or not, reaches the event log.

Each test is written so that removing the corresponding behaviour makes it
fail. A test that passes with the feature removed proves nothing.
"""

import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_os import syscall as sc  # noqa: E402
from agent_os.models import (  # noqa: E402
    Approval,
    ApprovalDecision,
    ApprovalScope,
    Job,
    JobState,
    Principal,
    utc_now,
)
from agent_os.service import ControlService  # noqa: E402


def make_job(job_id="job1"):
    """A minimal Job that satisfies the dataclass contract."""
    now = utc_now()
    return Job(
        id=job_id,
        mission_id="m1",
        title="t",
        proposed_by=Principal.PLANNER,
        executor="fake-executor",
        workspace_paths=("/w",),
        actions=("run_tests",),
        state=JobState.APPROVED,
        attempt_no=0,
        manifest_hash="h",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        command=None,
    )


def make_approval(job_id="job1", expires_at=None, manifest_hash="h"):
    now = utc_now()
    return Approval(
        id="ap1",
        job_id=job_id,
        decision=ApprovalDecision.GRANTED,
        scope=ApprovalScope(
            executor="fake-executor",
            workspace_paths=("/w",),
            actions=("run_tests",),
            command=None,
            action=None,
        ),
        requested_at=now.isoformat(),
        decided_at=now.isoformat(),
        decided_by=Principal.HUMAN,
        expires_at=expires_at,
        manifest_hash=manifest_hash,
    )


class SyscallEvaluateTest(unittest.TestCase):
    """The pure decision function: no service, no DB, no executor."""

    def test_unknown_action_is_denied_by_default(self):
        """A brand-new action name must be refused, not silently allowed."""
        req = sc.SyscallRequest(agent_id="a", action="launch_missiles", job_id="job1")
        verdict = sc.evaluate(req, make_job(), None, utc_now())
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, sc.REASON_UNKNOWN_ACTION)

    def test_missing_job_is_denied(self):
        req = sc.SyscallRequest(agent_id="a", action="dispatch", job_id="ghost")
        verdict = sc.evaluate(req, None, None, utc_now())
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, sc.REASON_NO_JOB)

    def test_no_approval_is_denied(self):
        req = sc.SyscallRequest(agent_id="a", action="dispatch", job_id="job1")
        verdict = sc.evaluate(req, make_job(), None, utc_now())
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "no_approval_record")

    def test_policy_exception_fails_closed(self):
        """The defining property: a crash in policy is DENY, never ALLOW."""
        import agent_os.syscall as mod

        original = mod.validate_dispatch

        def boom(*a, **k):
            raise RuntimeError("simulated policy crash")

        mod.validate_dispatch = boom
        try:
            req = sc.SyscallRequest(agent_id="a", action="dispatch", job_id="job1")
            verdict = sc.evaluate(req, make_job(), make_approval(), utc_now())
        finally:
            mod.validate_dispatch = original

        self.assertFalse(verdict.allowed, "a policy crash must DENY, not allow")
        self.assertEqual(verdict.reason, sc.REASON_POLICY_ERROR)

    def test_expired_approval_is_denied(self):
        past = utc_now() - timedelta(hours=1)
        req = sc.SyscallRequest(agent_id="a", action="dispatch", job_id="job1")
        verdict = sc.evaluate(req, make_job(), make_approval(expires_at=past), utc_now())
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "approval_expired")

    def test_manifest_mismatch_is_denied(self):
        """An approval for a different manifest must not authorize this job."""
        req = sc.SyscallRequest(agent_id="a", action="dispatch", job_id="job1")
        verdict = sc.evaluate(req, make_job(), make_approval(manifest_hash="OTHER"), utc_now())
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "manifest_changed_new_decision_required")

    def test_clean_request_is_allowed(self):
        """The gate must also say YES, or it is a wall, not a gate."""
        req = sc.SyscallRequest(agent_id="a", action="dispatch", job_id="job1")
        verdict = sc.evaluate(req, make_job(), make_approval(), utc_now())
        self.assertTrue(verdict.allowed, f"expected allow, got {verdict.reason}")
        self.assertEqual(verdict.reason, "allowed")


class SyscallServiceTest(unittest.TestCase):
    """The gate wired to a real service: verdicts are recorded, work is not run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.svc = ControlService(self.db)

    def tearDown(self):
        self.svc.close()
        self.tmp.cleanup()

    def test_verdict_is_written_to_the_event_log(self):
        req = sc.SyscallRequest(agent_id="agent-x", action="nope", job_id="j")
        sc.syscall(self.svc, req)
        kinds = [e["kind"] for e in self.svc.store.list_events()]
        self.assertIn("syscall_verdict", kinds)

    def test_denied_verdict_records_the_reason(self):
        req = sc.SyscallRequest(agent_id="agent-x", action="dispatch", job_id="ghost")
        verdict = sc.syscall(self.svc, req)
        self.assertFalse(verdict.allowed)
        events = [e for e in self.svc.store.list_events()
                  if e["kind"] == "syscall_verdict"]
        self.assertTrue(events)
        self.assertEqual(events[-1]["payload"]["reason"], sc.REASON_NO_JOB)


if __name__ == "__main__":
    unittest.main()
