# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

# -*- coding: utf-8 -*-
"""F3 — a timeout must leave NOTHING running, not just the direct child.

Measured before the fix: the executor reported the timeout honestly, and a
grandchild spawned by the child kept running after run() returned. The marker
file advanced from 58 to 82 during the 1.2s after the call returned. The
outcome was not a lie; the process tree was simply not cleaned up.

These tests pin the cleanup, and each one names the mechanism that must be
present for it to hold - a test that cannot tell a group kill from a single
kill is decoration.

Everything here is POSIX-only (option C, owner-approved): process-group
control is unavailable on Windows and the adapter now fails closed there
rather than shipping a branch no test in this suite could exercise.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from agent_os.adapters import subprocess_executor as se
from agent_os.adapters.subprocess_executor import SubprocessExecutor
from agent_os.models import (
    Job,
    JobState,
    Principal,
    WorkerLostError,
    encode_command,
)

POSIX_ONLY = not hasattr(os, "killpg")


def _spawner_argv(marker: Path) -> list:
    """A parent that spawns a stamping grandchild, then blocks forever.

    The parent must block, or the timeout never engages and nothing is being
    measured. The grandchild rewrites `marker` forever, so its survival is
    measured by the file changing - a ps listing can lie, a growing file
    cannot.
    """
    stamp = (
        "import time,pathlib\n"
        f"p = pathlib.Path({str(marker)!r})\n"
        "for i in range(100000):\n"
        "    p.write_text(str(i))\n"
        "    time.sleep(0.05)\n"
    )
    return [
        sys.executable, "-c",
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable,'-c',{stamp!r}])\n"
        "print('spawned', flush=True)\n"
        "time.sleep(100000)\n",
    ]


# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

class ProcessGroupTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="f3-test-"))
        self.src = self.tmp / "src"
        self.src.mkdir()
        (self.src / "calc.py").write_text("print('ok')\n", encoding="utf-8")
        self.marker = self.tmp / "alive.marker"
        self._spawned: list = []

    def tearDown(self):
        # Never leave a stray behind, even if a test fails midway. Sweep by
        # marker as well as by recorded proc, so an orphan the executor failed
        # to clean up is still reaped and cannot poison the next test.
        for p in self._spawned:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except OSError:
                pass
        for ln in self._orphans():
            try:
                pid = int(ln.split()[0])
                if pid != os.getpid():
                    os.kill(pid, signal.SIGKILL)
            except (ValueError, OSError):
                pass

    def _make_job(self, argv, executor):
        return Job(
            id="job-f3", mission_id="mission-f3", title="group cleanup",
            proposed_by=Principal.PLANNER,
            executor=executor.name,
            workspace_paths=(str(self.src),),
            actions=("run_command",),
            state=JobState.APPROVED, attempt_no=0, manifest_hash="x",
            created_at="t", updated_at="t",
            command=encode_command(argv),
        )

    def _still_stamping(self, settle=1.2) -> bool:
        if not self.marker.exists():
            return False
        before = self.marker.read_text()
        time.sleep(settle)
        return self.marker.read_text() != before

    def _orphans(self):
        """Live pids still holding the marker - the direct witness."""
        ps = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True,
                            text=True, timeout=20).stdout
        return [ln for ln in ps.splitlines() if str(self.marker) in ln]


class GrandchildSurvivesTheTimeout(ProcessGroupTestBase):
    @unittest.skipIf(POSIX_ONLY, "process groups are POSIX-only (owner option C)")
    def test_the_grandchild_is_dead_after_run_returns(self):
        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=2)
        out = ex.run(self._make_job(_spawner_argv(self.marker), ex), 1)

        # the timeout is still reported honestly - the fix must not change that
        self.assertEqual(out.evidence.get("reason"), "timeout")
        self.assertNotEqual(out.status, "completed_with_evidence")

        # THE defect: the grandchild used to keep stamping after run() returned
        self.assertFalse(
            self._still_stamping(),
            "a grandchild survived the timeout - the process group was not killed",
        )

    @unittest.skipIf(POSIX_ONLY, "process groups are POSIX-only (owner option C)")
    def test_no_orphan_is_left_behind(self):
        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=2)
        ex.run(self._make_job(_spawner_argv(self.marker), ex), 1)
        time.sleep(0.5)
        survivors = [ln for ln in subprocess.run(
            ["ps", "-eo", "pid,args"], capture_output=True, text=True,
            timeout=20).stdout.splitlines() if str(self.marker) in ln]
        self.assertEqual(survivors, [],
                         f"processes still holding the marker: {survivors}")


class TheMechanismIsActuallyPresent(ProcessGroupTestBase):
    """A kill of the whole group and a kill of one child look identical from
    the happy path. These assert the mechanism, so a regression to
    proc.kill() is caught by name rather than by luck."""

    def test_the_child_is_started_in_its_own_session(self):
        src = Path(se.__file__).read_text(encoding="utf-8")
        self.assertIn("start_new_session=True", src,
                      "the child must lead its own process group")
        # anchored on the Popen call itself, not on a mention in a comment
        i = src.find("subprocess.Popen(")
        self.assertGreater(i, 0)
        window = src[i:i + 700]
        self.assertIn("start_new_session=True", window,
                      "start_new_session is not on the Popen call")

    def test_the_timeout_path_kills_the_group_not_the_child(self):
        src = Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("except subprocess.TimeoutExpired:")
        self.assertGreater(i, 0)
        window = src[i:i + 300]
        self.assertIn("_kill_process_tree", window,
                      "the timeout path must kill the tree")
        self.assertNotIn("proc.kill()", window,
                         "the timeout path still kills only the direct child")

    def test_kill_process_tree_signals_the_group(self):
        src = Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("def _kill_process_tree")
        self.assertGreater(i, 0, "_kill_process_tree is not defined")
        window = src[i:i + 1200]
        self.assertIn("os.killpg", window)
        self.assertIn("SIGKILL", window)

    def test_a_finally_covers_the_interrupt_path(self):
        # KeyboardInterrupt derives from BaseException, so `except Exception`
        # cannot see it. Without a finally the process tree is abandoned.
        src = Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("    def run(")
        j = src.find("    @staticmethod", i)
        body = src[i:j]
        self.assertIn("finally:", body,
                      "run() has no finally, so a BaseException leaks a live tree")
        f = body.find("finally:")
        self.assertIn("_kill_process_tree", body[f:f + 600],
                      "the finally does not clean up the process tree")
        self.assertIn("child_pid", body[f:f + 600],
                      "the finally still guards on `proc`, which is None when "
                      "Popen raised after the fork")


class KeyboardInterruptDoesNotLeakTheTree(ProcessGroupTestBase):
    @unittest.skipIf(POSIX_ONLY, "process groups are POSIX-only (owner option C)")
    def test_an_interrupt_during_wait_still_kills_the_tree(self):
        """The second leak the register described: Ctrl-C during wait().

        The witness has to be the LIVE PROCESS, not the marker's motion. A
        first version of this test watched the marker and passed even with the
        finally's guard forced to `if False` - because the grandchild had
        already died, and a frozen marker cannot tell "killed by the executor"
        from "killed by the harness on the way out". So assert on pids.
        """
        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=60)
        real_popen = se.subprocess.Popen

        def interrupting_popen(*a, **kw):
            proc = real_popen(*a, **kw)
            self._spawned.append(proc)

            def boom(timeout=None):
                # let the grandchild get going before the interrupt lands
                for _ in range(40):
                    if self.marker.exists():
                        break
                    time.sleep(0.05)
                time.sleep(0.4)
                raise KeyboardInterrupt()
            proc.wait = boom
            return proc

        se.subprocess.Popen = interrupting_popen
        try:
            with self.assertRaises(KeyboardInterrupt):
                ex.run(self._make_job(_spawner_argv(self.marker), ex), 1)
        finally:
            se.subprocess.Popen = real_popen

        # the executor had its chance to clean up on the way out
        time.sleep(0.5)
        survivors = self._orphans()
        self.assertEqual(
            survivors, [],
            "KeyboardInterrupt abandoned live processes - the finally block "
            f"did not clean up the tree: {survivors}",
        )


class UnsupportedPlatformFailsClosed(ProcessGroupTestBase):
    def test_without_killpg_the_adapter_refuses_before_running(self):
        """Owner option C: no untested Windows branch. Fail closed instead."""
        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=2)
        argv = [sys.executable, "-c", "print('this must never run')"]
        job = self._make_job(argv, ex)

        original = ex.supports_process_groups
        ex.supports_process_groups = False
        try:
            with self.assertRaises(WorkerLostError) as ctx:
                ex.run(job, 1)
        finally:
            ex.supports_process_groups = original

        self.assertIn("killpg", str(ctx.exception))

    def test_the_platform_flag_matches_the_platform(self):
        # guards the test above from silently testing nothing
        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=2)
        self.assertEqual(ex.supports_process_groups, hasattr(os, "killpg"))


class OrdinaryRunsStillWork(ProcessGroupTestBase):
    def test_a_normal_command_still_completes(self):
        """The cleanup must not break the ordinary path."""
        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=30)
        argv = [sys.executable, "-c", "print('5 tests passed')"]
        out = ex.run(self._make_job(argv, ex), 1)
        self.assertEqual(out.evidence.get("exit_code"), 0)
        self.assertIn("5 tests passed", out.evidence["diff"])

    def test_a_fast_failing_command_still_reports_its_exit_code(self):
        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=30)
        argv = [sys.executable, "-c", "import sys; sys.exit(3)"]
        out = ex.run(self._make_job(argv, ex), 1)
        self.assertEqual(out.evidence.get("exit_code"), 3)
        self.assertEqual(out.status, "completed_missing_evidence")


class TheSignalMustBeUnignorable(ProcessGroupTestBase):
    """Why SIGKILL and not SIGTERM - made observable rather than asserted.

    A mutation that swaps SIGKILL for SIGTERM survived the suite, and the test
    was RIGHT to stay green: the stamping grandchild is a plain loop that does
    not handle SIGTERM, so the two signals are equivalent for it. A mutation
    that cannot change behaviour proves nothing.

    The discriminating workload is a child that IGNORES SIGTERM - the case the
    choice of SIGKILL exists for. If the executor sent SIGTERM, this would
    survive; with SIGKILL it cannot.
    """

    @unittest.skipIf(POSIX_ONLY, "process groups are POSIX-only (owner option C)")
    def test_a_sigterm_ignoring_child_is_still_killed(self):
        stubborn = (
            "import signal,time,pathlib\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"p=pathlib.Path({str(self.marker)!r})\n"
            "for i in range(100000):\n"
            "    p.write_text(str(i))\n"
            "    time.sleep(0.05)\n"
        )
        argv = [sys.executable, "-c",
                "import subprocess,sys,time\n"
                f"subprocess.Popen([sys.executable,'-c',{stubborn!r}])\n"
                "time.sleep(100000)\n"]

        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=2)
        out = ex.run(self._make_job(argv, ex), 1)
        self.assertEqual(out.evidence.get("reason"), "timeout")

        time.sleep(0.6)
        self.assertEqual(
            self._orphans(), [],
            "a child that ignores SIGTERM survived - the executor must be "
            "using SIGKILL, not SIGTERM",
        )

    def test_the_implementation_uses_sigkill(self):
        src = Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("def _kill_process_tree")
        window = src[i:i + 1400]
        self.assertIn("signal.SIGKILL", window)
        self.assertNotIn(
            "os.killpg(os.getpgid(target), signal.SIGTERM)", window,
            "the group kill must be SIGKILL so a child trapping SIGTERM "
            "cannot outlive the timeout",
        )


class TheExceptPathIsAlsoCleanedUp(ProcessGroupTestBase):
    """The second cleanup path, and the one a mutation revealed was untested.

    Removing the `except Exception` cleanup survived the suite. Measured: that
    branch is only reachable when run() raises an ordinary Exception AFTER
    Popen succeeded, and no test made that happen. KeyboardInterrupt is a
    BaseException and takes the finally instead - which is why the two paths
    are complementary rather than redundant, and why only removing BOTH lets
    the grandchild survive.
    """

    @unittest.skipIf(POSIX_ONLY, "process groups are POSIX-only (owner option C)")
    def test_an_ordinary_error_after_popen_still_kills_the_tree(self):
        """Exercise the `except Exception` cleanup with a child that is alive.

        The failure has to be an ordinary Exception raised INSIDE the `try`
        that wraps Popen, while the child is still running. Three earlier
        attempts failed for measurable reasons and are worth not repeating:
        breaking _write_meta sits AFTER the try/except/finally; rebinding
        `open` at module scope does not exist there and leaked into builtins;
        and making Popen itself raise after the fork is a case Python already
        reaps (measured: a Popen that raises leaks nothing), and one no pid
        bookkeeping inside run() could ever cover, because the pid never
        reaches run().

        So the failure is injected on the first wait() instead - inside the
        try, with the process tree already up.
        """
        ex = SubprocessExecutor(source_workspace=self.src, timeout_seconds=30)
        argv = _spawner_argv(self.marker)

        real_popen = se.subprocess.Popen
        state = {"pid": None, "raised": False}

        def spawn_then_fail_on_wait(*a, **kw):
            proc = real_popen(*a, **kw)
            state["pid"] = proc.pid
            self._spawned.append(proc)

            def failing_wait(timeout=None):
                # let the grandchild get going, then fail inside the try
                for _ in range(40):
                    if self.marker.exists():
                        break
                    time.sleep(0.05)
                time.sleep(0.3)
                if not state["raised"]:
                    state["raised"] = True
                    raise OSError("simulated failure while the child runs")
                # later calls (the finally's own wait) must behave normally
                proc.wait = real_popen_wait
                return real_popen_wait(timeout)

            real_popen_wait = proc.wait
            proc.wait = failing_wait
            return proc

        se.subprocess.Popen = spawn_then_fail_on_wait
        try:
            with self.assertRaises(WorkerLostError):
                ex.run(self._make_job(argv, ex), 1)
        finally:
            se.subprocess.Popen = real_popen

        self.assertIsNotNone(state["pid"], "Popen was never reached")
        self.assertTrue(state["raised"], "the injected failure never fired")
        time.sleep(0.6)
        self.assertEqual(
            self._orphans(), [],
            "the except-Exception path abandoned a live process tree",
        )


if __name__ == "__main__":
    unittest.main()
