# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""M2 (B2): executor evidence is redacted on WRITE (event log) and on
READ (the /api/jobs/{id}/evidence endpoint).

Raw stdout can carry whatever the command printed; F5 once demonstrated
`password=hunter2` arriving at the evidence endpoint unredacted."""

from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os.api import AgentOSApi
from agent_os.logging_setup import register_secret
from agent_os.models import (
    ApprovalDecision,
    JobState,
    Principal,
    WorkerOutcome,
)
from agent_os.service import ControlService

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
T2 = T0 + timedelta(hours=2)

LIVE_SECRET = "b2-redaction-live-secret-9f2c"

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class _LeakyAdapter:
    """Reports success while its evidence contains real-looking secrets."""

    name = "leaky-executor"
    allowed_actions = frozenset({"read_file", "write_file", "run_tests"})

    def run(self, job, attempt):
        return WorkerOutcome(
            status="completed_with_evidence",
            evidence={
                # Harmless text LEADS (it must survive); every secret sits on
                # the tail, and redaction may consume a secret's tail
                # aggressively - over-redaction is the safe direction.
                "diff": (
                    "surviving-marker|line one password=hunter2\n"
                    "Authorization: ghp_1234567890abcdef\n"
                    f"LIVE={LIVE_SECRET}"
                ),
                "test_report": "3 tests passed",
                "exit_code": 0,
            },
        )


class EvidenceRedactionTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)
        register_secret(LIVE_SECRET)

    def tearDown(self):
        self.svc.close()

    def _dispatched_job(self):
        mission = self.svc.create_mission("redact evidence", now=T0)
        self.svc.activate_mission(mission.id)
        job = self.svc.record_proposal(
            mission_id=mission.id,
            title="leaky",
            executor="leaky-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            proposed_by=Principal.PLANNER,
            now=T0,
        )
        approval = self.svc.request_approval(job.id, expires_at=T2, now=T0)
        self.svc.decide(approval.id, ApprovalDecision.GRANTED, Principal.HUMAN, now=T0)
        self.svc.dispatch(
            job.id, _LeakyAdapter(), now=T0 + timedelta(minutes=30)
        )
        # record_proposal's job is a pre-dispatch snapshot; state lives in
        # the store (exactly what this test must read).
        fresh = self.svc.store.get_job(job.id)
        self.assertIsNotNone(fresh)
        return fresh

    def test_persisted_event_evidence_is_redacted(self):
        job = self._dispatched_job()
        self.assertEqual(job.state, JobState.COMPLETED_VERIFIED)
        events = [
            e
            for e in self.svc.store.list_events()
            if e["kind"] == "job_completed_verified"
            and e["payload"].get("job_id") == job.id
        ]
        self.assertTrue(events, "no persisted evidence event")
        diff = events[-1]["payload"]["evidence"]["diff"]
        self.assertNotIn("hunter2", diff, "password= value survived redaction")
        self.assertNotIn("ghp_1234567890abcdef", diff, "GitHub token survived")
        self.assertNotIn(LIVE_SECRET, diff, "registered live secret survived")
        # not erased wholesale: the harmless prefix survives
        self.assertIn("surviving-marker", diff)

    def test_evidence_endpoint_returns_redacted_copy(self):
        job = self._dispatched_job()
        api = AgentOSApi(self.svc, "t")
        payload = api._job_evidence(job.id)
        diff = payload["evidence"]["diff"]
        self.assertNotIn("hunter2", diff)
        self.assertNotIn("ghp_1234567890abcdef", diff)
        self.assertNotIn(LIVE_SECRET, diff)
        self.assertIn("surviving-marker", diff)


if __name__ == "__main__":
    unittest.main(verbosity=2)
