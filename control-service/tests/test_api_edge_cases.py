# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""B2 edge cases, all through the HTTP handler (the path a browser takes):

- L1: a naive expires_at is normalised at the edge (was: TypeError -> 500)
- L2: DELETE /api/tools/registry/ without an id is 404 (was: IndexError -> 500)
- A3: deciding an absent approval is 404 (was: assert -> 500)
- M3: serve() refuses a non-loopback host
"""

from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os.adapters.fake import FakeExecutor
from agent_os.api import (
    AgentOSApi,
    register_executor,
    serve,
    unregister_executor,
)
from agent_os.models import ApprovalDecision, Principal
from agent_os.service import ControlService

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
T2 = T0 + timedelta(hours=2)

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class ApiEdgeCasesTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)
        register_executor("fake-executor", FakeExecutor(behavior="success"))
        self.addCleanup(unregister_executor, "fake-executor")
        self.api = AgentOSApi(self.svc, "t")

    def tearDown(self):
        self.svc.close()

    def _job(self, title):
        mission = self.svc.create_mission(title, now=T0)
        self.svc.activate_mission(mission.id)
        return self.svc.record_proposal(
            mission_id=mission.id,
            title=title,
            executor="fake-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            proposed_by=Principal.PLANNER,
            now=T0,
        )

    # -- L2 -------------------------------------------------------------

    def test_tools_delete_without_id_is_404_not_500(self):
        status, body = self.api.handle("DELETE", "/api/tools/registry/", None)
        self.assertEqual(status, 404, body)

    # -- A3 -------------------------------------------------------------

    def test_decide_on_absent_approval_is_404_not_500(self):
        status, body = self.api.handle(
            "POST", "/api/approvals/no-such-approval/decide",
            {"decision": "granted"},
        )
        self.assertEqual(status, 404, body)

    # -- L1 -------------------------------------------------------------

    def test_naive_future_expiry_is_normalised_and_dispatches(self):
        job = self._job("naive future")
        st, approval = self.api.handle(
            "POST", "/api/approvals",
            {"job_id": job.id, "expires_at": "2199-01-01T00:00:00"},
        )
        self.assertEqual(st, 201, approval)
        parsed = datetime.fromisoformat(approval["expires_at"])
        self.assertIsNotNone(
            parsed.tzinfo, "a naive expires_at must be stored timezone-aware"
        )
        st, _ = self.api.handle(
            "POST", f"/api/approvals/{approval['id']}/decide",
            {"decision": "granted"},
        )
        self.assertEqual(st, 200)
        st, body = self.api.handle(
            "POST", f"/api/jobs/{job.id}/dispatch", {}
        )
        self.assertEqual(st, 200, body)
        self.assertEqual(body["receipt"]["final_state"], "completed_verified")

    def test_naive_past_expiry_refuses_cleanly_not_500(self):
        job = self._job("naive past")
        st, approval = self.api.handle(
            "POST", "/api/approvals",
            {"job_id": job.id, "expires_at": "2000-01-01T00:00:00"},
        )
        self.assertEqual(st, 201, approval)
        # Phase 2: decide() passes through the syscall gate, which refuses
        # expired approvals with 403 (PermissionError). The approval stays
        # REQUESTED, so dispatch is refused with approval_not_granted.
        st, _ = self.api.handle(
            "POST", f"/api/approvals/{approval['id']}/decide",
            {"decision": "granted"},
        )
        self.assertEqual(st, 403)
        st, body = self.api.handle(
            "POST", f"/api/jobs/{job.id}/dispatch", {}
        )
        self.assertEqual(st, 409, body)
        self.assertIn("approval_not_granted", body["error"]["message"])

    # -- M3 -------------------------------------------------------------

    def test_serve_refuses_a_non_loopback_host(self):
        with self.assertRaises(ValueError):
            serve(self.svc, host="0.0.0.0", port=0, token="t")


if __name__ == "__main__":
    unittest.main(verbosity=2)
