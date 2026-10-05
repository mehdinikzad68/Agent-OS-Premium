# -*- coding: utf-8 -*-
"""F6 — a failed cleanup must be visible, on EVERY path that cleans up.

The first version of this file tested only the happy path, and mutation
checking said so: 7 mutants survived, 6 of them because the timeout,
executor-error, fail-closed and copy-failed paths had no test at all. The
mutants were valid; the coverage was missing. So every path is now driven.

The witness is the RECORD, not the log and not the return value: a failure that
exists only in a log line is gone by the time anyone goes looking.
"""

import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from agent_os.adapters import subprocess_executor as se
from agent_os.adapters.subprocess_executor import (
    SubprocessExecutor,
    _discard_sandbox,
    clear_failed_cleanups,
    failed_cleanups,
)
from agent_os.models import (
    Job,
    JobState,
    Principal,
    WorkerLostError,
    encode_command,
)

ROOT_RULES = (
    "A permission-based test proves nothing as root, and silently passing as"
    " one is how a test becomes theatre. Detect it explicitly rather than"
    " letting the assertion decide."
)


def _am_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

class TheRecordItself(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f6-rec-"))
        clear_failed_cleanups()

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            try:
                if p.is_dir() and not p.is_symlink():
                    os.chmod(p, 0o700)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        clear_failed_cleanups()

    def _undeletable(self):
        victim = self.tmp / "locked"
        victim.mkdir()
        (victim / "held.txt").write_text("x", encoding="utf-8")
        os.chmod(victim, 0o500)
        return victim

    @unittest.skipIf(_am_root(), ROOT_RULES)
    def test_a_failed_delete_is_recorded_not_swallowed(self):
        victim = self._undeletable()
        ok = _discard_sandbox(victim, "test-why")

        self.assertFalse(ok, "the delete reported success on a failure")
        recs = failed_cleanups()
        self.assertEqual(len(recs), 1, f"expected one record, got {recs}")
        self.assertEqual(recs[0]["why"], "test-why")
        self.assertEqual(recs[0]["sandbox"], str(victim))
        self.assertTrue(recs[0]["error"])
        self.assertTrue(recs[0]["still_present"])

    def test_a_successful_delete_records_nothing(self):
        victim = self.tmp / "fine"
        victim.mkdir()
        (victim / "a.txt").write_text("x", encoding="utf-8")

        self.assertTrue(_discard_sandbox(victim, "ok"))
        self.assertFalse(victim.exists())
        self.assertEqual(failed_cleanups(), [],
                         "a successful delete must not be reported as a failure")

    @unittest.skipIf(_am_root(), ROOT_RULES)
    def test_a_failure_is_logged_as_well_as_recorded(self):
        """M5 survived the first mutation run: nothing asserted the log call."""
        victim = self._undeletable()
        with self.assertLogs(se._log, level="WARNING") as cm:
            _discard_sandbox(victim, "log-why")
        joined = "\n".join(cm.output)
        self.assertIn("sandbox cleanup failed", joined)
        self.assertIn("log-why", joined)
        self.assertIn(str(victim), joined)

    def test_the_cap_is_applied_by_the_code_not_by_the_test(self):
        """M7 survived because the old test sliced the list by hand.

        Drive the real function past the cap and require the list to stop
        growing - so removing the cap line inside _discard_sandbox fails here.
        """
        cap = se._CLEANUP_LOG_CAP
        victim = self.tmp / "locked"
        victim.mkdir()
        (victim / "held.txt").write_text("x", encoding="utf-8")

        def always_fail(p, *a, **kw):
            raise PermissionError("simulated")

        with mock.patch.object(se.shutil, "rmtree", always_fail):
            for i in range(cap + 25):
                _discard_sandbox(victim, f"fill-{i}")

        self.assertEqual(len(failed_cleanups()), cap,
                         "the record list grew past its cap")
        self.assertEqual(failed_cleanups()[-1]["why"], f"fill-{cap + 24}",
                         "the cap must drop the OLDEST entries, not the newest")

    def test_failed_cleanups_hands_out_a_copy(self):
        """M13 survived: a live list would let a caller corrupt the record."""
        victim = self.tmp / "locked"
        victim.mkdir()
        with mock.patch.object(se.shutil, "rmtree",
                               side_effect=PermissionError("x")):
            _discard_sandbox(victim, "copy-check")

        got = failed_cleanups()
        self.assertTrue(got)
        got.clear()
        self.assertEqual(len(failed_cleanups()), 1,
                         "failed_cleanups() returned the live list; a caller "
                         "can erase the evidence the record exists to keep")

    def test_no_call_site_still_swallows_a_failure(self):
        src = pathlib.Path(se.__file__).read_text(encoding="utf-8")
        self.assertNotIn("rmtree(sandbox, ignore_errors=True)", src,
                         "a live call site still uses ignore_errors=True")
        self.assertNotIn("shutil.rmtree(sandbox, ignore_errors", src)


class EveryCleanupPathRecordsItsFailure(unittest.TestCase):
    """One test per cleanup site: the finding was five sites, so five tests."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f6-path-"))
        self.src = self.tmp / "ws"
        self.src.mkdir()
        (self.src / "a.py").write_text("print('6 tests passed')\n",
                                       encoding="utf-8")
        self.ex_root = self.tmp / "sandboxes"
        self._patchers = []
        clear_failed_cleanups()

    def tearDown(self):
        # stop our own fakes FIRST: the cleanup below must use the real rmtree
        for p in reversed(self._patchers):
            p.stop()
        self._patchers.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)
        clear_failed_cleanups()

    def _executor(self, **kw):
        kw.setdefault("timeout_seconds", 20)
        return SubprocessExecutor(source_workspace=self.src,
                                  sandbox_root=self.ex_root, **kw)

    def _job(self, argv, ex):
        return Job(
            id="job-f6", mission_id="m", title="t",
            proposed_by=Principal.PLANNER, executor=ex.name,
            workspace_paths=(str(self.src),), actions=("run_command",),
            state=JobState.APPROVED, attempt_no=0, manifest_hash="x",
            created_at="t", updated_at="t", command=encode_command(argv),
        )

    def _fake_rmtree(self, boom):
        patcher = mock.patch.object(se.shutil, "rmtree", boom)
        patcher.start()
        self._patchers.append(patcher)
        return patcher

    def _break_rmtree(self):
        def boom(p, *a, **kw):
            raise PermissionError("simulated: cannot delete")
        self._fake_rmtree(boom)

    def _assert_recorded(self, why):
        recs = failed_cleanups()
        self.assertTrue(recs, f"the {why} path cleaned up with no record")
        self.assertEqual(recs[-1]["why"], why)

    def test_path_completed(self):
        ex = self._executor()
        self._break_rmtree()
        out = ex.run(self._job([sys.executable, "-c", "print('ok')"], ex), 1)
        self.assertEqual(out.evidence.get("exit_code"), 0)
        self._assert_recorded("completed")

    def test_path_timeout(self):
        ex = self._executor(timeout_seconds=1)
        self._break_rmtree()
        out = ex.run(self._job(
            [sys.executable, "-c", "import time; time.sleep(60)"], ex), 1)
        self.assertEqual(out.evidence.get("reason"), "timeout")
        self._assert_recorded("timeout")

    def test_path_executor_error(self):
        ex = self._executor()
        self._break_rmtree()
        with mock.patch.object(se.subprocess, "Popen",
                               side_effect=OSError("simulated: cannot fork")):
            with self.assertRaises(WorkerLostError):
                ex.run(self._job([sys.executable, "-c", "print('ok')"], ex), 1)
        self._assert_recorded("executor-error")

    def test_path_no_process_group_support(self):
        ex = self._executor()
        self._break_rmtree()
        with mock.patch.object(type(ex), "supports_process_groups", False):
            with self.assertRaises(WorkerLostError) as ctx:
                ex.run(self._job([sys.executable, "-c", "print('ok')"], ex), 1)
        self.assertIn("process group", str(ctx.exception))
        self._assert_recorded("no-process-group-support")

    def test_path_copy_failed(self):
        ex = self._executor()
        self._break_rmtree()
        with mock.patch.object(se, "_copytree_into",
                               side_effect=OSError("simulated: copy failed")):
            with self.assertRaises(WorkerLostError) as ctx:
                ex.run(self._job([sys.executable, "-c", "print('ok')"], ex), 1)
        self.assertIn("prepare", str(ctx.exception))
        self._assert_recorded("copy-failed")

    def test_every_reason_label_is_used_exactly_once(self):
        """Five sites, five labels. A copy-paste that reused one would hide
        which path failed, which is the whole content of the record."""
        src = pathlib.Path(se.__file__).read_text(encoding="utf-8")
        for lab in ("completed", "timeout", "executor-error",
                    "no-process-group-support", "copy-failed"):
            self.assertEqual(src.count(f'_discard_sandbox(sandbox, "{lab}")'), 1,
                             f"the label {lab!r} is not used exactly once")


if __name__ == "__main__":
    unittest.main()
