"""Subprocess executor tests: disposable workspace, timeout, evidence,
and fail-closed (no command => never verified).

These run a REAL subprocess (the Python interpreter) but only ever inside
a disposable temp copy of a throwaway source dir — never the live repo.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from agent_os.adapters.subprocess_executor import SubprocessExecutor
from agent_os.models import (
    Job,
    JobState,
    Principal,
    utc_now,
)
from agent_os.service import ControlService

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


def _make_job(command=None, executor="subprocess-executor", actions=("run_tests",)):
    job = Job(
        id="job-test",
        mission_id="mission-test",
        title="run a real command",
        proposed_by=Principal.PLANNER,
        executor=executor,
        workspace_paths=("w/",),
        actions=actions,
        state=JobState.APPROVED,
        attempt_no=0,
        manifest_hash="x",
        created_at="t",
        updated_at="t",
        command=command,
    )
    return job


class SubprocessExecutorTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.src = TMP / "src"
        self.src.mkdir(exist_ok=True)
        (self.src / "marker.txt").write_text("original", encoding="utf-8")
        self.sandbox_root = TMP / "sandboxes"
        self.sandbox_root.mkdir(exist_ok=True)

    def _runner(self, timeout=30, keep=False):
        return SubprocessExecutor(
            self.src, timeout_seconds=timeout, keep_workspace=keep,
            sandbox_root=self.sandbox_root,
        )

    def test_no_command_fails_closed_unverified(self):
        """Without a command, the executor must not guess: result is unverified."""
        job = _make_job(command=None)
        outcome = self._runner().run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertIn("no command", outcome.evidence.get("error", ""))

    def test_successful_command_produces_verified_evidence(self):
        job = _make_job(command=[sys.executable, "-c", "print('3 tests passed')"])
        outcome = self._runner().run(job, 1)
        self.assertEqual(outcome.status, "completed_with_evidence")
        self.assertTrue(outcome.evidence["test_report"])
        self.assertEqual(outcome.evidence["exit_code"], 0)

    def test_failing_command_is_unverified_even_with_exit_nonzero(self):
        job = _make_job(command=[sys.executable, "-c", "import sys; sys.exit(1)"])
        outcome = self._runner().run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertEqual(outcome.evidence["exit_code"], 1)
        # exit != 0 and no test signal => no test_report
        self.assertEqual(outcome.evidence["test_report"], "")

    def test_original_workspace_not_modified(self):
        """The source workspace must never be touched by the executor."""
        before = (self.src / "marker.txt").read_text()
        job = _make_job(command=[sys.executable, "-c", "print('ok')"])
        self._runner().run(job, 1)
        self.assertEqual((self.src / "marker.txt").read_text(), before)
        # no stray artifacts left in source
        self.assertEqual(sorted(p.name for p in self.src.iterdir()), ["marker.txt"])

    def test_timeout_is_honest_not_success(self):
        job = _make_job(command=[sys.executable, "-c", "import time; time.sleep(5)"])
        outcome = self._runner(timeout=1).run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertEqual(outcome.evidence.get("reason"), "timeout")

    def test_command_in_manifest_hash(self):
        """Changing the command changes the manifest hash => invalidates a grant."""
        a = _make_job(command=["python", "-c", "print('a')"])
        b = _make_job(command=["python", "-c", "print('b')"])
        self.assertNotEqual(a.compute_manifest_hash(), b.compute_manifest_hash())


class MigrationTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)

    def test_v1_database_migrates_to_v2(self):
        """A DB created under v1 schema gains the `command` column on open."""
        import sqlite3

        db = TMP / "migration.db"
        if db.exists():
            db.unlink()
        # Build a v1-schema DB by hand (jobs without command column).
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta VALUES ('schema_version','1')")
        conn.commit()
        conn.close()

        svc = ControlService(db)  # opens and migrates
        try:
            cols = [r[1] for r in svc.store.conn.execute("PRAGMA table_info(jobs)").fetchall()]
            self.assertIn("command", cols)
            ver = svc.store.conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()["value"]
            self.assertEqual(ver, "2")
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
