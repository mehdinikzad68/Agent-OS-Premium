# -*- coding: utf-8 -*-
"""Permanent regression tests for the project registry service.

These paths had no coverage at all, and it showed twice: an `import os` slip
and then a log_event() keyword collision both shipped with all 98 tests green,
because nothing in the suite ever called register_project or remove_project.

Deliberately no HTTP here. tests/test_api.py and the live scratch probes cover
the transport; this file is about the service contract, so a failure points at
the service instead of at urllib.
"""
import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_os.logging_setup import log_event  # noqa: E402
from agent_os.service import (  # noqa: E402
    REASON_SCOPE_UNSET,
    ControlService,
    ProjectRejected,
)

REAL = Path("/home/mehdi/workspace/wp-bioscentiran")


# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

class ProjectServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "p.db"
        self.svc = ControlService(self.db)
        self.addCleanup(self.svc.close)
        self.scope = Path(self.tmp.name) / "scope"
        self.scope.mkdir()
        self.good = self.scope / "site"
        self.good.mkdir()
        self._env = dict(os.environ)
        os.environ["AGENT_OS_PROJECT_SCOPE"] = str(self.scope)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env)

    def register(self, **kw):
        args = {"name": "site", "environment": "wsl", "root": str(self.good)}
        args.update(kw)
        return self.svc.register_project(**args)

    # ---------------------------------------------------------------- success
    def test_registers_and_returns_the_project(self):
        p = self.register()
        self.assertEqual(p.name, "site")
        self.assertEqual(p.environment, "wsl")
        self.assertEqual(p.canonical_root, str(self.good))

    def test_list_projects_returns_what_was_registered(self):
        self.register()
        rows = self.svc.list_projects()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].canonical_root, str(self.good))

    def test_a_duplicate_pair_stays_a_single_row(self):
        """The store keeps (environment, canonical_root) unique. The service
        surfaces that as a refusal, so the second call raises and the row
        count is still 1 - the pair was never duplicated."""
        self.register()
        with self.assertRaises(ProjectRejected):
            self.register()
        self.assertEqual(len(self.svc.list_projects()), 1)

    def test_a_second_registration_is_refused_as_duplicate(self):
        self.register()
        with self.assertRaises(ProjectRejected) as ctx:
            self.register(name="other name")
        self.assertEqual(ctx.exception.reason, "duplicate")

    # ---------------------------------------------------------------- removal
    def test_remove_project_removes_the_row(self):
        p = self.register()
        self.assertTrue(self.svc.remove_project(p.id))
        self.assertEqual(self.svc.list_projects(), [])

    def test_remove_project_on_an_unknown_id_returns_false(self):
        self.assertFalse(self.svc.remove_project("project-does-not-exist"))

    def test_remove_project_is_not_confused_by_a_similarly_named_id(self):
        p = self.register()
        self.assertFalse(self.svc.remove_project(p.id + "x"))
        self.assertTrue(self.svc.remove_project(p.id))
        self.assertEqual(self.svc.list_projects(), [])

    def test_removal_leaves_the_registered_folder_untouched(self):
        before = sorted(os.listdir(self.good))
        p = self.register()
        self.svc.remove_project(p.id)
        self.assertEqual(sorted(os.listdir(self.good)), before)
        self.assertTrue(self.good.is_dir())

    def test_the_project_survives_reopening_the_database(self):
        p = self.register()
        self.svc.close()
        again = ControlService(self.db)
        self.addCleanup(again.close)
        self.assertEqual([r.id for r in again.list_projects()], [p.id])

    # ---------------------------------------------------------------- refusals
    def test_a_root_outside_the_scope_is_refused(self):
        with self.assertRaises(ProjectRejected) as ctx:
            self.register(root="/etc")
        self.assertEqual(ctx.exception.reason, "outside_scope")

    def test_a_missing_root_is_refused(self):
        with self.assertRaises(ProjectRejected) as ctx:
            self.register(root=str(self.scope / "absent"))
        self.assertEqual(ctx.exception.reason, "missing")

    def test_a_relative_root_is_refused(self):
        with self.assertRaises(ProjectRejected) as ctx:
            self.register(root="relative/path")
        self.assertEqual(ctx.exception.reason, "not_absolute")

    def test_windows_is_refused_rather_than_half_supported(self):
        with self.assertRaises(ProjectRejected) as ctx:
            self.register(environment="windows")
        self.assertEqual(ctx.exception.reason, "windows_unsupported")

    def test_an_unset_scope_falls_back_to_home_workspace(self):
        """The documented default: with the env var absent, $HOME/workspace is
        the scope. A project inside it registers; one outside is refused."""
        home = Path(self.tmp.name) / "home"
        inside = home / "workspace" / "site"
        inside.mkdir(parents=True)
        del os.environ["AGENT_OS_PROJECT_SCOPE"]
        os.environ["HOME"] = str(home)

        p = self.register(root=str(inside))
        self.assertEqual(p.canonical_root, str(inside))

        with self.assertRaises(ProjectRejected) as ctx:
            self.register(root="/etc", name="etc")
        self.assertEqual(ctx.exception.reason, "outside_scope")

    def test_a_scope_with_no_safe_default_fails_closed(self):
        """Unset env var AND no $HOME/workspace: there is no defensible scope,
        so registration must be refused rather than fall back to something
        broad like / or the home directory itself."""
        del os.environ["AGENT_OS_PROJECT_SCOPE"]
        os.environ["HOME"] = str(self.scope / "no-home-here")
        with self.assertRaises(ProjectRejected) as ctx:
            self.register()
        self.assertEqual(ctx.exception.reason, REASON_SCOPE_UNSET)

    def test_a_symlink_escaping_the_scope_is_refused(self):
        link = self.scope / "escape"
        link.symlink_to("/etc")
        with self.assertRaises(ProjectRejected) as ctx:
            self.register(root=str(link))
        self.assertEqual(ctx.exception.reason, "symlink_escapes_scope")

    def test_a_symlink_inside_the_scope_is_accepted_and_flagged(self):
        link = self.scope / "inner"
        link.symlink_to(self.good)
        p = self.register(root=str(link))
        self.assertTrue(p.is_symlink)
        self.assertEqual(p.canonical_root, str(self.good))

    def test_a_refused_registration_leaves_no_row(self):
        for root in ("/etc", "relative/path", str(self.scope / "absent")):
            with self.assertRaises(ProjectRejected):
                self.register(root=root)
        self.assertEqual(self.svc.list_projects(), [])

    # ---------------------------------------------------------------- logging
    def test_the_lifecycle_reaches_the_structured_log(self):
        """The gap that made this file necessary: project_registered existed in
        the event table but never in the JSON-lines log."""
        with self.assertLogs("agent_os", level=logging.INFO) as caught:
            p = self.register()
            self.svc.remove_project(p.id)
        joined = "\n".join(caught.output)
        self.assertIn("project.registered", joined)
        self.assertIn("project.removed", joined)

    def test_a_refusal_is_logged_at_warning_with_its_reason(self):
        """The reason has to be a structured field. An operator answering
        "why was this path refused?" months later greps the log, and a reason
        buried in a human sentence is not greppable."""
        with self.assertLogs("agent_os", level=logging.WARNING) as caught:
            with self.assertRaises(ProjectRejected):
                self.register(root="/etc")
        rejected = [r for r in caught.records if r.getMessage() == "project.rejected"]
        self.assertEqual(len(rejected), 1, "expected one project.rejected record")
        self.assertEqual(getattr(rejected[0], "reason", None), "outside_scope")

    def test_log_event_rejects_a_field_named_name(self):
        """The trap that shipped a broken success path: log_event's third
        parameter is `name`, so a data field of the same name collides."""
        logger = logging.getLogger("agent_os.test_collision")
        with self.assertRaises(TypeError):
            log_event(logger, logging.INFO, "some.event", name="payload")

    # ---------------------------------------------------------------- storage
    def test_the_event_table_records_both_transitions(self):
        p = self.register()
        self.svc.remove_project(p.id)
        conn = sqlite3.connect(self.db)
        try:
            kinds = {row[0] for row in conn.execute("SELECT kind FROM events")}
        finally:
            conn.close()
        self.assertIn("project_registered", kinds)
        self.assertIn("project_removed", kinds)

    def test_a_refusal_records_no_event(self):
        with self.assertRaises(ProjectRejected):
            self.register(root="/etc")
        conn = sqlite3.connect(self.db)
        try:
            n = conn.execute(
                "SELECT count(*) FROM events WHERE kind = 'project_registered'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 0)

    @unittest.skipUnless(REAL.is_dir(), "the real project folder is not present")
    def test_the_real_project_registers(self):
        """The one case that cannot be faked: a real WSL path, real
        permissions, real stat() results."""
        os.environ["AGENT_OS_PROJECT_SCOPE"] = "/home/mehdi/workspace"
        p = self.register(root=str(REAL))
        self.assertEqual(p.canonical_root, str(REAL))
        self.assertFalse(p.is_symlink)


if __name__ == "__main__":
    unittest.main()
