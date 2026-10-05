# -*- coding: utf-8 -*-
"""F9 — the copy must not descend through a symlink; F10 — the scope is not a
client-supplied parameter.

F9: `child.is_dir()` follows a link, so a link pointing at an ancestor was
recursed into until the OS refused with ELOOP, and the operator saw a raw errno
inside a generic "failed to prepare" message. Measured as a robustness defect,
not a leak: a link to a sibling is an escape and F5's guard refuses it, so the
only links reaching the copy point inward.

F10: register_project advertised a `scope` parameter that no caller could
supply - the HTTP handler never passed it, and neither does any of the other
eight call sites. A parameter nobody can reach reads as a control the operator
can turn.
"""
import inspect
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from agent_os import service as service_mod
from agent_os.adapters import subprocess_executor as se
from agent_os.adapters.subprocess_executor import _copytree_into
from agent_os.service import ControlService, ProjectRejected, project_scope
from agent_os.store import Store

POSIX_ONLY = os.name != "posix"


# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

class CopyDoesNotDescendThroughLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f9-test-"))
        self.src = self.tmp / "ws"
        self.src.mkdir()
        # NOTE: deliberately no plain.txt here - two tests below assert an
        # exact listing, and an unexpected fixture file made them fail for a
        # reason that had nothing to do with symlinks.
        self.dst = self.tmp / "dst"
        self.dst.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_link_to_an_ancestor_no_longer_breaks_the_copy(self):
        (self.src / "plain.txt").write_text("plain\n", encoding="utf-8")
        (self.src / "sub").mkdir()
        (self.src / "sub" / "real.txt").write_text("real\n", encoding="utf-8")
        os.symlink(str(self.src), str(self.src / "sub" / "up"))

        # Before the fix this raised OSError(Errno 40) after recursing until
        # the OS gave up. The witness is the copy completing, not the absence
        # of an exception.
        _copytree_into(self.src, self.dst)

        self.assertTrue((self.dst / "sub" / "real.txt").exists(),
                        "a real file must still be copied")
        # plain.txt is created in setUp for this test only, before the copy,
        # so the assertion is about the copy and not about test ordering.
        kept = self.dst / "sub" / "up"
        # is_symlink() is the check that matters. kept.is_dir() FOLLOWS the
        # link and is True here, so a rglob through it would walk back into
        # the source - the exact behaviour under test.
        self.assertTrue(kept.is_symlink(),
                        "the link must be copied AS a link, not followed")
        self.assertEqual(os.readlink(kept), str(self.src))

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_an_inner_link_is_skipped_not_followed(self):
        (self.src / "inside").mkdir()
        (self.src / "inside" / "lib.py").write_text("x = 1\n", encoding="utf-8")
        os.symlink(str(self.src / "inside"), str(self.src / "vendor"))

        _copytree_into(self.src, self.dst)

        kept = self.dst / "vendor"
        self.assertTrue(kept.is_symlink(),
                        "an inner link must survive as a link")
        self.assertEqual(os.readlink(kept), str(self.src / "inside"))

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_file_link_is_skipped_too(self):
        (self.src / "real.txt").write_text("real\n", encoding="utf-8")
        os.symlink(str(self.src / "real.txt"), str(self.src / "alias.txt"))

        _copytree_into(self.src, self.dst)

        self.assertTrue((self.dst / "real.txt").exists())
        self.assertTrue((self.dst / "alias.txt").is_symlink())

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_the_skip_is_logged_not_silent(self):
        (self.src / "inside").mkdir()
        os.symlink(str(self.src / "inside"), str(self.src / "vendor"))
        with self.assertLogs(se._log, level="INFO") as cm:
            _copytree_into(self.src, self.dst)
        self.assertTrue(any("symlink" in m for m in cm.output),
                        "keeping a link instead of its target must be visible")

    @unittest.skipIf(POSIX_ONLY, "symlink creation is POSIX-shaped here")
    def test_a_link_nested_inside_a_subdirectory_is_also_kept_as_a_link(self):
        """The case the first version of this fix missed.

        It skipped links at the top level but left the recursive copytree on
        its default, so a link INSIDE a subdirectory was still followed - the
        same defect one level down. This is the test that would have caught it.
        """
        deep = self.src / "pkg" / "inner"
        deep.mkdir(parents=True)
        (deep / "real.py").write_text("y = 2\n", encoding="utf-8")
        os.symlink(str(self.src), str(deep / "back"))

        _copytree_into(self.src, self.dst)

        kept = self.dst / "pkg" / "inner" / "back"
        self.assertTrue(kept.is_symlink(),
                        f"a nested link was followed instead of kept: "
                        f"{kept.exists()}")
        self.assertTrue((self.dst / "pkg" / "inner" / "real.py").exists())

    def test_the_recursive_copy_is_told_not_to_follow_links(self):
        src = pathlib.Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("def _copytree_into")
        d = src.find('"""', src.find('"""', i) + 3)
        body = src[d:i + 4200]
        self.assertIn("symlinks=True", body,
                      "the recursive copy must be told to keep links, not "
                      "follow them - that was the nested defect")

    def test_a_workspace_without_links_is_copied_whole(self):
        (self.src / "a.txt").write_text("a\n", encoding="utf-8")
        (self.src / "d").mkdir()
        (self.src / "d" / "b.txt").write_text("b\n", encoding="utf-8")

        _copytree_into(self.src, self.dst)

        got = sorted(str(p.relative_to(self.dst)) for p in self.dst.rglob("*"))
        self.assertEqual(got, ["a.txt", "d", "d/b.txt"])

    def test_ignored_names_still_apply(self):
        (self.src / ".git").mkdir()
        (self.src / ".git" / "config").write_text("x\n", encoding="utf-8")
        (self.src / "__pycache__").mkdir()
        (self.src / "__pycache__" / "m.pyc").write_text("x\n", encoding="utf-8")
        (self.src / "keep.txt").write_text("k\n", encoding="utf-8")

        _copytree_into(self.src, self.dst)

        names = sorted(p.name for p in self.dst.rglob("*"))
        self.assertNotIn(".git", names)
        self.assertNotIn("__pycache__", names)
        self.assertIn("keep.txt", names)

    def test_the_code_skips_links_before_asking_is_dir(self):
        src = pathlib.Path(se.__file__).read_text(encoding="utf-8")
        i = src.find("def _copytree_into")
        # skip the docstring: it explains the defect and names is_dir() in
        # prose, which is how the first version of this test matched prose
        d = src.find('"""', src.find('"""', i) + 3)
        body = src[d:i + 4200]
        sym = body.find("is_symlink()")
        isdir = body.find("child.is_dir()")
        self.assertGreater(sym, 0, "the copy no longer checks for links")
        self.assertGreater(isdir, 0)
        self.assertLess(sym, isdir,
                        "the symlink check must come first; is_dir() follows "
                        "a link, so checking it first is the original defect")


class ScopeIsNotAClientParameter(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f10-"))
        self.inner = self.tmp / "allowed"
        self.inner.mkdir()
        self.outer = self.tmp / "elsewhere"
        self.outer.mkdir()
        (self.outer / "x").mkdir()
        (self.outer / "x" / "file.txt").write_text("x\n", encoding="utf-8")
        self.db = self.tmp / "s.db"
        # A path, not a Store - see test_serve_socket for why that matters.
        self.svc = ControlService(self.db)
        self._old_scope = os.environ.get(service_mod.PROJECT_SCOPE_ENV)
        os.environ[service_mod.PROJECT_SCOPE_ENV] = str(self.tmp)

    def tearDown(self):
        if self._old_scope is None:
            os.environ.pop(service_mod.PROJECT_SCOPE_ENV, None)
        else:
            os.environ[service_mod.PROJECT_SCOPE_ENV] = self._old_scope
        try:
            self.svc.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_signature_no_longer_advertises_a_scope(self):
        sig = inspect.signature(ControlService.register_project)
        self.assertNotIn("scope", sig.parameters,
                         "a parameter no caller can supply reads as a control "
                         "the operator can turn")

    def test_the_scope_still_comes_from_configuration(self):
        self.assertEqual(project_scope(), str(self.tmp))
        p = self.svc.register_project(name="p", environment="wsl",
                                      root=str(self.inner))
        self.assertTrue(p.canonical_root.startswith(str(self.tmp)))

    def test_a_root_outside_the_configured_scope_is_still_refused(self):
        outside = pathlib.Path("/etc")
        with self.assertRaises(ProjectRejected):
            self.svc.register_project(name="q", environment="wsl",
                                      root=str(outside))

    def test_no_caller_anywhere_tries_to_pass_scope(self):
        """The measurement that motivated F10, kept as a test."""
        D = pathlib.Path(service_mod.__file__).resolve().parent.parent
        offenders = []
        for p in D.rglob("*.py"):
            if "__pycache__" in str(p):
                continue
            text = p.read_text(encoding="utf-8")
            i = 0
            while True:
                i = text.find("register_project(", i)
                if i < 0:
                    break
                seg = text[i:i + 300]
                if "scope=" in seg.split(")")[0]:
                    offenders.append(f"{p.name}: {seg.splitlines()[0][:70]}")
                i += 1
        self.assertEqual(offenders, [],
                         f"a caller passes scope= again: {offenders}")

    def test_an_unset_scope_refuses_every_registration(self):
        """M9 survived the first mutation run: this path had no test.

        With no scope configured there is no boundary at all, so the only safe
        answer is to refuse - not to fall back to a cwd, a home directory, or
        the root of the filesystem.

        ~/workspace EXISTS on this machine and project_scope() falls back to
        it, so unsetting the environment variable is not enough: a test that
        only unsets it would measure the wrong branch entirely. Patch the
        resolver, which is the bare global register_project looks up.
        """
        os.environ.pop(service_mod.PROJECT_SCOPE_ENV, None)
        with mock.patch.object(service_mod, "project_scope", return_value=None):
            self.assertIsNone(service_mod.project_scope())
            with self.assertRaises(ProjectRejected) as ctx:
                self.svc.register_project(name="r", environment="wsl",
                                          root=str(self.inner))
        self.assertIn(service_mod.PROJECT_SCOPE_ENV, str(ctx.exception),
                      "the refusal must say which variable to set")

    def test_the_http_handler_cannot_widen_the_scope(self):
        """A client must not be able to name its own boundary."""
        from agent_os import api as api_mod
        src = inspect.getsource(api_mod.AgentOSApi._post)
        i = src.find("/api/projects")
        seg = src[i:src.find("/api/missions", i)]
        self.assertNotIn("scope", seg,
                         "the projects endpoint must not read a scope field")


if __name__ == "__main__":
    unittest.main()
