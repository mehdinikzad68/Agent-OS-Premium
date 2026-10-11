# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""A2 (B2): an executor that raises anything other than WorkerLostError
must not leave the job RUNNING forever.

Before the fix the job stayed in RUNNING: A6 then answered
duplicated=True for every retry and reconcile() refuses non-INTERRUPTED
states, so the job became unreachable. Now it ends FAILED, an event says
why, and a later dispatch is an honest idempotent replay."""

from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os.models import ApprovalDecision, DispatchRefused, JobState, Principal
from agent_os.service import ControlService

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
T2 = T0 + timedelta(hours=2)

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class _BoomAdapter:
    """Fails during preparation, before any work happens."""

    name = "boom-executor"
    allowed_actions = frozenset({"read_file", "write_file", "run_tests"})

    def run(self, job, attempt):
        raise RuntimeError("sandbox preparation exploded")


class ExecutorFailureLeavesRecoverableStateTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)

    def tearDown(self):
        self.svc.close()

    def _approved_job(self):
        mission = self.svc.create_mission("boom", now=T0)
        self.svc.activate_mission(mission.id)
        job = self.svc.record_proposal(
            mission_id=mission.id,
            title="executor explodes",
            executor="boom-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            proposed_by=Principal.PLANNER,
            now=T0,
        )
        approval = self.svc.request_approval(job.id, expires_at=T2, now=T0)
        self.svc.decide(approval.id, ApprovalDecision.GRANTED, Principal.HUMAN, now=T0)
        return job

    def test_broken_executor_ends_failed_not_running(self):
        job = self._approved_job()
        clock = T0 + timedelta(minutes=30)
        with self.assertRaises(RuntimeError):
            self.svc.dispatch(job.id, _BoomAdapter(), now=clock)

        stored = self.svc.store.get_job(job.id)
        self.assertEqual(
            stored.state, JobState.FAILED,
            f"job left in {stored.state}; RUNNING would make it unreachable",
        )
        kinds = [e["kind"] for e in self.svc.store.list_events()]
        self.assertIn("dispatch_failed", kinds)

    def test_a_failed_job_dispatch_is_an_idempotent_replay(self):
        job = self._approved_job()
        clock = T0 + timedelta(minutes=30)
        with self.assertRaises(RuntimeError):
            self.svc.dispatch(job.id, _BoomAdapter(), now=clock)

        receipt = self.svc.dispatch(job.id, _BoomAdapter(), now=clock)
        self.assertTrue(receipt.duplicated, "replay must not re-run anything")
        self.assertEqual(receipt.final_state, JobState.FAILED)

    def test_worker_lost_still_maps_to_interrupted_unknown(self):
        class _Lost:
            name = "lost-executor"
            allowed_actions = frozenset({"run_tests"})

            def run(self, job, attempt):
                from agent_os.models import WorkerLostError

                raise WorkerLostError("worker vanished")

        job = self._approved_job()
        receipt = self.svc.dispatch(
            job.id, _Lost(), now=T0 + timedelta(minutes=30)
        )
        self.assertEqual(receipt.final_state, JobState.INTERRUPTED_UNKNOWN)


if __name__ == "__main__":
    unittest.main(verbosity=2)
