# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""The single-path test: dispatch() MUST go through the syscall gate.

The claim under test (docs/KERNEL-GAP.md, Phase 1 acceptance criterion 1):

    There is exactly ONE path from an approved proposal to execution, and
    that path passes the syscall gate. Removing or bypassing the gate
    must make dispatch() fail loudly, never silently fall back to the old
    direct-policy path.

Three properties, each with a falsifier that kills a fake implementation:

  1. SINGLE PATH  - gate stubbed to "always deny": a dispatch that SHOULD
     succeed now fails. Falsifies the bypass: if dispatch() could reach the
     executor without the gate, the wall would change nothing and this
     would pass vacuously - so it must fail in that world.
  2. REAL POLICY  - gate stubbed to "always allow": a dispatch with NO
     grant is still refused. Falsifies hardcoded allowed=True at the call
     site: the refusal must come from the REAL policy inside the gate's
     jurisdiction, not from a copy or a bypass around the stub.
  3. NOT MOOT     - with the real gate, an approved dispatch still
     succeeds end to end and the executor runs exactly once. Falsifies
     the wall: wiring the gate must not break the happy path.

Property 2 subtlety: the allow-all stub replaces the gate, so the refusal
cannot come from the gate itself - it must come from policy code that the
dispatch() wiring still consults. In the wired dispatch() the refusal fires
at the A2 policy re-check (validate_dispatch over latest_approval_for_job,
which returns no approval for an ungranted job); the atomic spend
(consume_approval) is the second real enforcement behind it. Either way an
allow-all stub cannot reach the executor without a real, unspent approval.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_os import syscall as sc  # noqa: E402
from agent_os.adapters.fake import FakeExecutor  # noqa: E402
from agent_os.models import (  # noqa: E402
    ApprovalDecision,
    DispatchRefused,
    Principal,
)
from agent_os.service import ControlService  # noqa: E402

T0 = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
T_LATER = T0 + timedelta(minutes=30)


class SinglePathTest(unittest.TestCase):
    """dispatch() may reach the executor only through the syscall gate."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = ControlService(os.path.join(self.tmp.name, "t.db"))
        mission = self.svc.create_mission("single-path")
        self.svc.activate_mission(mission.id)
        self.mission_id = mission.id
        self.adapter = FakeExecutor()

    def tearDown(self):
        self.svc.close()
        self.tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def _propose(self, command=("echo", "wired")):
        """Planner proposes a job; returns the job record."""
        return self.svc.record_proposal(
            mission_id=self.mission_id,
            title="wired",
            executor="fake-executor",
            workspace_paths=(self.tmp.name,),
            actions=("run_tests",),
            proposed_by=Principal.PLANNER,
            command=list(command),
        )

    def _grant(self, job):
        """Human grants the job's pending approval.

        Expiry is strictly AFTER the dispatch time (T_LATER) so the policy
        check passes; policy refuses now >= expires_at.
        """
        approval = self.svc.request_approval(
            job.id, expires_at=T_LATER + timedelta(hours=2), now=T0
        )
        self.svc.decide(approval.id, ApprovalDecision.GRANTED, Principal.HUMAN, now=T0)
        return approval

    # -- 1. SINGLE PATH --------------------------------------------------
    def test_1_gate_is_on_the_only_path(self):
        """Always-deny wall: the should-succeed dispatch must be refused."""
        job = self._propose()
        self._grant(job)

        original = sc.syscall
        sc.syscall = lambda *a, **k: sc.SyscallVerdict(
            allowed=False, reason="wall_for_test",
            action="dispatch", agent_id="test", job_id=job.id,
        )
        try:
            with self.assertRaises(DispatchRefused):
                self.svc.dispatch(job.id, self.adapter, now=T_LATER)
        finally:
            sc.syscall = original
        # the wall must have been consulted, and nothing may have run
        self.assertEqual(self.adapter.invocations, [])

    # -- 2. REAL POLICY --------------------------------------------------
    def test_2_allow_all_stub_cannot_bypass_real_policy(self):
        """Always-allow stub: an ungranted job must STILL be refused.

        The refusal cannot come from the stubbed gate; it must come from
        the real enforcement still on the path AFTER the gate (the atomic
        approval spend). This kills a wiring that hardcodes "allowed"
        and then runs the executor regardless of approval state.
        """
        job = self._propose()
        # NOTE: deliberately NO grant.

        original = sc.syscall
        sc.syscall = lambda *a, **k: sc.SyscallVerdict(
            allowed=True, reason="allow_all_for_test",
            action="dispatch", agent_id="test", job_id=job.id,
        )
        try:
            with self.assertRaises(DispatchRefused):
                self.svc.dispatch(job.id, self.adapter, now=T_LATER)
        finally:
            sc.syscall = original
        self.assertEqual(self.adapter.invocations, [])

    # -- 3. NOT MOOT -----------------------------------------------------
    def test_3_real_gate_happy_path_still_executes_once(self):
        """Real gate, approved job: dispatch succeeds, executor runs once."""
        job = self._propose()
        self._grant(job)

        receipt = self.svc.dispatch(job.id, self.adapter, now=T_LATER)
        self.assertFalse(receipt.duplicated)
        self.assertEqual(len(self.adapter.invocations), 1)

        # The verdict was recorded in the audit trail with the exact shape
        # the gate module documents: kind="syscall_verdict", allowed=True.
        verdicts = [
            e for e in self.svc.store.list_events()
            if e["kind"] == "syscall_verdict"
            and e["payload"].get("job_id") == job.id
        ]
        self.assertEqual(len(verdicts), 1, "exactly one verdict per dispatch")
        self.assertTrue(verdicts[0]["payload"]["allowed"])


if __name__ == "__main__":
    unittest.main()
