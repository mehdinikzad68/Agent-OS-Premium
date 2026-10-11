# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""B3 invariants (review 2026-10-05, LOW findings):

- record_proposal refuses a mission that never existed (the schema
  declares no FOREIGN KEY, so referential integrity lives here)
- the package version matches pyproject (the 0.1.0/0.2.0 drift closed)
"""

from __future__ import annotations

import pathlib
import re
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

import agent_os
from agent_os.models import Principal
from agent_os.service import ControlService

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class B3InvariantTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)

    def tearDown(self):
        self.svc.close()

    def test_proposal_for_a_missing_mission_is_refused(self):
        """No orphan jobs: the mission must exist first (FK lives in code)."""
        with self.assertRaises(KeyError):
            self.svc.record_proposal(
                mission_id="mission-that-never-existed",
                title="ghost",
                executor="fake-executor",
                workspace_paths=("w/",),
                actions=("run_tests",),
                proposed_by=Principal.PLANNER,
                now=T0,
            )

    def test_proposal_after_create_mission_still_works(self):
        """The new check must not break the normal path."""
        mission = self.svc.create_mission("real", now=T0)
        job = self.svc.record_proposal(
            mission_id=mission.id,
            title="fine",
            executor="fake-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            proposed_by=Principal.PLANNER,
            now=T0,
        )
        self.assertEqual(job.mission_id, mission.id)

    def test_package_version_matches_pyproject(self):
        pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
        m = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(m, "pyproject has no version line")
        self.assertEqual(
            agent_os.__version__, m.group(1),
            "agent_os.__version__ drifted from pyproject",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
