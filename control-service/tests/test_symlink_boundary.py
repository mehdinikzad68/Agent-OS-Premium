# -*- coding: utf-8 -*-
"""F5 — an escaping symlink must not carry outside content into a run.

Measured before the fix: a symlink named `innocent_link` pointing at a
directory caused copytree (symlinks=False, the default) to copy that
directory's real contents into the run directory:

    innocent_link/           [REAL]
    innocent_link/id_rsa     [REAL]  PRIVATE KEY MATERIAL
    innocent_link/credentials[REAL]  password=hunter2

and a command could read them, with the executor publishing stdout in evidence
and /api/jobs/<id>/evidence returning it over HTTP.

These tests pin the refusal. The witness is the FILE SYSTEM, not the message:
a test that only checks the error text would still pass if the copy happened
first and the error came afterwards.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from agent_os.adapters import subprocess_executor as se
from agent_os.adapters.subprocess_executor import (
    SubprocessExecutor,
    _find_escaping_links,
)
from agent_os.models import (
    Job,
    JobState,
    Principal,
    WorkerLostError,
    encode_command,
)

POSIX_ONLY = os.name != "posix"


class SymlinkTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f5-test-"))
        self.src = self.tmp / "workspace"
        self.src.mkdir()
        (self.src / "normal.py").write_text("print('1 test passed')\n",
                                             encoding="utf-8")
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        (self.outside / "id_rsa").write_text("PRIVATE KEY MATERIAL\n",
                                             encoding="utf-8")
        (self.outside / "credentials").write_text("password=hunter2\n",
                                                  encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _executor(self, **kw):
        return SubprocessExecutor(
            source_workspace=self.src,
            timeout_seconds=20,
            sandbox_root=self.tmp / "sandboxes",
            **kw,
        )

    def _job(self, argv, ex):
        return Job(
            id="job-f5", mission_id="m", title="t",
            proposed_by=Principal.PLANNER, executor=ex.name,
            workspace_paths=(str(self.src),), actions=("run_command",),
            state=JobState.APPROVED, attempt_no=0, manifest_hash="x",
            created_at="t", updated_at="t", command=encode_command(argv),
        )

    def _sandbox_contents(self):
        root = self.tmp / "sandboxes"
        if not root.exists():
            return []
        return sorted(p.name for p in root.rglob("*"))


class EscapingLinksAreRefused(SymlinkTestBase):
    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_directory_link_outside_refuses_the_run(self):
        os.symlink(str(self.outside), str(self.src / "innocent_link"))
        ex = self._executor()
        with self.assertRaises(WorkerLostError) as ctx:
            ex.run(self._job([sys.executable, "-c", "print('hi')"], ex), 1)
        self.assertIn("innocent_link", str(ctx.exception),
                      "the message must name the offending path")

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_file_link_outside_is_refused_too(self):
        # The directory case is the obvious one. A link to a single FILE takes
        # the copy2 branch instead of the copytree branch, and copied content
        # just as readily - measured, it produced a real file.
        os.symlink(str(self.outside / "id_rsa"), str(self.src / "notes.txt"))
        ex = self._executor()
        with self.assertRaises(WorkerLostError) as ctx:
            ex.run(self._job([sys.executable, "-c", "print('hi')"], ex), 1)
        self.assertIn("notes.txt", str(ctx.exception))

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_link_nested_at_depth_is_refused(self):
        # A top-level scan would miss this entirely, which is why the guard
        # walks. Assert on the depth case explicitly.
        deep = self.src / "a" / "b" / "c"
        deep.mkdir(parents=True)
        os.symlink(str(self.outside), str(deep / "deep_link"))
        ex = self._executor()
        with self.assertRaises(WorkerLostError) as ctx:
            ex.run(self._job([sys.executable, "-c", "print('hi')"], ex), 1)
        self.assertIn("deep_link", str(ctx.exception))

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_sibling_sharing_a_prefix_is_still_an_escape(self):
        # /tmp/x/workspace does not contain /tmp/x/workspaces. is_within exists
        # to refuse this, and the guard must inherit that behaviour.
        sibling = self.tmp / "workspaces"
        sibling.mkdir()
        os.symlink(str(sibling), str(self.src / "prefix_trap"))
        ex = self._executor()
        with self.assertRaises(WorkerLostError) as ctx:
            ex.run(self._job([sys.executable, "-c", "print('hi')"], ex), 1)
        self.assertIn("prefix_trap", str(ctx.exception))

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_nothing_is_copied_when_the_run_is_refused(self):
        """The witness is the filesystem.

        A guard that raised AFTER the copy would still produce the right error
        message while the secrets sat in the run directory. This is the check
        that distinguishes the two.
        """
        os.symlink(str(self.outside), str(self.src / "innocent_link"))
        ex = self._executor()
        with self.assertRaises(WorkerLostError):
            ex.run(self._job([sys.executable, "-c", "print('hi')"], ex), 1)

        leaked = [n for n in self._sandbox_contents()
                  if "id_rsa" in n or "credentials" in n or "innocent" in n]
        self.assertEqual(leaked, [],
                         f"the refused run still copied: {leaked}")

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_the_secret_contents_do_not_reach_evidence(self):
        """End to end over the real executor, not just the guard."""
        os.symlink(str(self.outside), str(self.src / "innocent_link"))
        ex = self._executor(keep_workspace=True)
        with self.assertRaises(WorkerLostError):
            ex.run(self._job(
                [sys.executable, "-c",
                 "print(open('innocent_link/credentials').read())"], ex), 1)
        # nothing ran, so no evidence exists at all
        self.assertEqual(self._sandbox_contents(), [],
                         "a run directory was created despite the refusal")


class LinksThatStayInsideAreFine(SymlinkTestBase):
    """Option A, stated explicitly: a self-referential link is not an escape.

    Refusing ordinary projects over a link that points inside their own tree
    would be a regression bought for nothing.
    """

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_link_inside_the_workspace_does_not_block_the_run(self):
        (self.src / "inside").mkdir()
        (self.src / "inside" / "lib.py").write_text("x = 1\n", encoding="utf-8")
        os.symlink(str(self.src / "inside"), str(self.src / "vendor"))

        self.assertEqual(_find_escaping_links(self.src), [])

        ex = self._executor()
        out = ex.run(self._job(
            [sys.executable, "-c", "print('3 tests passed')"], ex), 1)
        self.assertEqual(out.evidence.get("exit_code"), 0)
        self.assertIn("3 tests passed", out.evidence["diff"])

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_clean_workspace_is_unaffected(self):
        self.assertEqual(_find_escaping_links(self.src), [])
        ex = self._executor()
        out = ex.run(self._job(
            [sys.executable, "-c", "print('4 tests passed')"], ex), 1)
        self.assertEqual(out.evidence.get("exit_code"), 0)


    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_link_pointing_at_an_ancestor_is_not_an_escape(self):
        """A self-referential link is inside, so it is allowed - and must terminate.

        This also pins a property two surviving mutations exposed: neither
        os.walk(src) nor os.walk(src, followlinks=True) can detect a link whose
        realpath is inside the workspace, so those mutations were meaningless
        rather than tests being weak. The real traversal risk is descending
        through a link to an ANCESTOR, which never ends - hence this test, and
        hence the explicit dirnames.remove() rather than relying on the flag.
        """
        (self.src / "sub").mkdir()
        os.symlink(str(self.src), str(self.src / "sub" / "up"))

        # must return promptly rather than walking forever
        self.assertEqual(_find_escaping_links(self.src), [])

        # The guard allows it - the target is inside - and since F9 the COPY
        # handles it too: a link is copied AS a link, so there is no
        # recursion and no ELOOP. This test pinned the old behaviour, which
        # failed closed with a raw errno; it now pins the fixed behaviour,
        # which is that such a project simply runs.
        #
        # The safety claim is unchanged and still asserted above: the guard
        # does not hang, and does not report an inside link as an escape.
        ex = self._executor()
        out = ex.run(self._job(
            [sys.executable, "-c", "print('the run proceeds')"], ex), 1)
        self.assertEqual(out.evidence.get("exit_code"), 0)
        self.assertIn("the run proceeds", out.evidence["diff"])

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_self_referential_link_never_lands_outside_the_sandbox(self):
        """The link is preserved, so nothing points out of the tree.

        F9 copies the link rather than its target. That is safe here only
        because the guard has already refused anything escaping - so the
        preserved link necessarily points at content the copy is taking
        anyway. This asserts the link is inert, not merely present.
        """
        (self.src / "sub").mkdir()
        (self.src / "sub" / "real.txt").write_text("real\n", encoding="utf-8")
        os.symlink(str(self.src), str(self.src / "sub" / "up"))

        ex = self._executor(keep_workspace=True)
        out = ex.run(self._job(
            [sys.executable, "-c", "print('ok')"], ex), 1)
        self.assertEqual(out.evidence.get("exit_code"), 0)
        sandbox = pathlib.Path(out.evidence["sandbox"])
        try:
            kept = sandbox / "sub" / "up"
            self.assertTrue(kept.is_symlink(),
                            "the link must be preserved, not followed")
            self.assertEqual(os.readlink(kept), str(self.src))
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_the_walk_does_not_descend_through_links(self):
        # followlinks=False AND the explicit dirnames.remove(). Either alone
        # would do; the belt-and-braces is deliberate, because a link to an
        # ancestor would hang the server's request thread.
        src = pathlib.Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("def _find_escaping_links")
        # the docstring alone is ~1300 chars, so a small window only ever sees
        # prose and never the code - anchor on the end of the docstring
        d = src.find('"""', src.find('"""', i) + 3)
        window = src[d:i + 2200]
        self.assertIn("followlinks=False", window,
                      "the walk must not follow symlinks")
        self.assertIn("dirnames.remove(name)", window,
                      "the guard must stop descending at a link it just recorded")


class TheGuardIsActuallyWiredIn(SymlinkTestBase):
    """The guard existing is not the same as run() calling it."""

    def test_run_calls_the_guard_before_making_the_sandbox(self):
        src = pathlib.Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("    def run(")
        j = src.find("    @staticmethod", i)
        body = src[i:j]
        g = body.find("_find_escaping_links")
        self.assertGreater(g, 0, "run() never calls the symlink guard")
        mk = body.find("sandbox.mkdir()")
        self.assertGreater(mk, 0)
        self.assertLess(
            g, mk,
            "the guard must run BEFORE the sandbox is created, otherwise a "
            "refused run still leaves a directory behind",
        )

    def test_the_copy_still_uses_the_default_that_follows_links(self):
        # If this ever becomes symlinks=True the guard is still required -
        # a preserved link is still readable. Pin the fact so the reasoning
        # is visible when someone considers the flag.
        src = pathlib.Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("def _copytree_into")
        self.assertGreater(i, 0)
        self.assertIn("copytree", src[i:i + 500])


if __name__ == "__main__":
    unittest.main()
