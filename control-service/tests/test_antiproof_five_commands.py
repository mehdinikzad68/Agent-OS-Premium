# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Phase 1 anti-proof: five commands a permissive gate allows, this gate refuses.

The claim this file tests (see docs/KERNEL-GAP.md section 6):

    The five commands below are ones a permissive approval gate lets through
    with no prompt. This kernel must refuse every one of them without an
    explicit, matching, unspent approval.

Three cases per command, because a gate that always says NO is a wall, not a
gate:

  A. no approval at all              -> DENY  (deny by default)
  B. approval naming a DIFFERENT cmd -> DENY  (byte-exact command binding)
  C. approval naming THE SAME cmd    -> ALLOW (the gate can open)

Case C is load-bearing. Without it a `return False` stub would pass A and B
and this suite would prove nothing.

This test drives the real ControlService over a real SQLite store and calls
the real syscall gate. Nothing here is mocked.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_os import syscall as sc  # noqa: E402
from agent_os.models import (  # noqa: E402
    ApprovalDecision,
    ApprovalScope,
    Principal,
)
from agent_os.service import ControlService  # noqa: E402

#: Five real-world operations a developer agent might request. None is
#: inherently malicious; the point is that the gate must not run any of them
#: without an approval that names that exact command.
FIVE_COMMANDS = [
    ["git", "push", "origin", "main"],
    ["docker", "rm", "-f", "some-container"],
    ["curl", "-X", "POST", "https://example.com/hook"],
    ["wsl", "-e", "bash", "-c", "echo hi"],
    ["sudo", "apt", "install", "some-pkg"],
]


class FiveCommandAntiProofTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = ControlService(os.path.join(self.tmp.name, "t.db"))
        mission = self.svc.create_mission("anti-proof")
        self.svc.activate_mission(mission.id)
        self.mission_id = mission.id

    def tearDown(self):
        self.svc.close()
        self.tmp.cleanup()

    def _propose(self, argv):
        return self.svc.record_proposal(
            mission_id=self.mission_id,
            title="cmd",
            executor="subprocess-executor",
            workspace_paths=(self.tmp.name,),
            actions=("run_tests",),
            proposed_by=Principal.PLANNER,
            command=list(argv),
        )

    def _grant_for(self, job, command_scope):
        """Request + grant an approval whose scope names `command_scope`."""
        approval = self.svc.request_approval(
            job_id=job.id,
            scope=ApprovalScope(
                executor=job.executor,
                workspace_paths=job.workspace_paths,
                actions=job.actions,
                command=command_scope,
                action=job.actions[0],
            ),
        )
        return self.svc.decide(approval.id, ApprovalDecision.GRANTED, Principal.HUMAN)

    def _verdict(self, job):
        req = sc.SyscallRequest(agent_id="agent", action="dispatch", job_id=job.id)
        return sc.syscall(self.svc, req)

    # ---- case A -------------------------------------------------------
    def test_A_no_approval_denies_every_command(self):
        for argv in FIVE_COMMANDS:
            job = self._propose(argv)
            verdict = self._verdict(job)
            self.assertFalse(
                verdict.allowed,
                f"{argv} was ALLOWED with no approval (reason={verdict.reason})",
            )
            self.assertEqual(verdict.reason, "no_approval_record")

    # ---- case B -------------------------------------------------------
    def test_B_mismatched_approval_denies_every_command(self):
        """An approval for a DIFFERENT command must not authorize this one.

        request_approval copies the command from the job, so to model a
        mismatch we grant against one job and then dispatch a *different*
        job that shares the approval's shape but carries another command.
        The manifest hash changes with the command, so the gate must refuse.
        """
        for argv in FIVE_COMMANDS:
            approved_job = self._propose(["echo", "approved"])
            self._grant_for(approved_job, approved_job.command)
            # A different job with a different command: same mission/executor,
            # so a naive "an approval exists for this mission" check would let
            # it through. The byte-exact binding must not.
            target = self._propose(argv)
            verdict = self._verdict(target)
            self.assertFalse(
                verdict.allowed,
                f"{argv} was ALLOWED on another job's approval "
                f"(reason={verdict.reason})",
            )

    # ---- case C (the falsifier) ---------------------------------------
    def test_C_matching_approval_allows_the_command(self):
        """The gate must OPEN for the exact approved command.

        Without this case a stub that always denies would pass A and B.
        """
        for argv in FIVE_COMMANDS:
            job = self._propose(argv)
            self._grant_for(job, job.command)
            verdict = self._verdict(job)
            self.assertTrue(
                verdict.allowed,
                f"{argv} was DENIED despite a matching approval "
                f"(reason={verdict.reason})",
            )


if __name__ == "__main__":
    unittest.main()
