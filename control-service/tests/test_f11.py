"""F11 and the two UI defects, held by tests that were written from the defect.

Three claims, each measured before the fix:

  1. a path with no id segment answers 404, not 500. The 500 was an
     IndexError on parts[2] raised before any lookup, not a missing None guard -
     _mission_public already raised KeyError and the dispatcher already caught
     it. A test asserting 404 would pass against a wrong fix, so each route is
     probed separately and the body is checked too.
  2. activating a mission that does not exist writes NOTHING. The old order
     recorded the event before the assert, so the feed gained a
     mission_activated for a mission that never existed. That is the
     interesting part, and a status-code test would never see it.
  3. the diagnostics panel shows the status and path it captured. The fields
     were stored and never rendered, so a warning could not be traced.

Run against a live HTTP server, not a stub: the dispatcher is what turns an
exception into a status, and a unit test of _get() would miss that entirely.
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

D = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(D))

TOKEN = "f11-test-token"
PORT = "8877"
PORT2 = "8875"   # the no-write class needs its own server


class MissingResourceIs404Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f11-"))
        env = dict(os.environ, AGENT_OS_TOKEN=TOKEN)
        cls.proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "agent_os.cli", "serve",
             "--host", "127.0.0.1", "--port", PORT,
             "--db", str(cls.tmp / "f11.db")],
            cwd=str(D), env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        cls.base = f"http://127.0.0.1:{PORT}"
        end = time.time() + 40
        while time.time() < end:
            try:
                cls._raw("/api/status")
                return
            except Exception:
                time.sleep(0.25)
        raise AssertionError("server did not start")

    @classmethod
    def tearDownClass(cls):
        try:
            os.killpg(os.getpgid(cls.proc.pid), signal.SIGKILL)
            cls.proc.wait(timeout=10)
        except OSError:
            pass
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _raw(cls, path, method="GET", body=None):
        headers = {"Authorization": f"Bearer {TOKEN}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            cls.base + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    # -- 1. no id segment ------------------------------------------------

    def test_a_mission_path_with_no_id_is_404(self):
        st, body = self._raw("/api/missions/")
        self.assertEqual(st, 404, body)
        self.assertEqual(json.loads(body)["error"]["code"], "not_found")

    def test_a_job_path_with_no_id_is_404(self):
        st, body = self._raw("/api/jobs/")
        self.assertEqual(st, 404, body)

    def test_an_approval_path_with_no_id_is_404(self):
        st, body = self._raw("/api/approvals/")
        self.assertEqual(st, 404, body)

    def test_activating_with_no_id_is_404(self):
        st, body = self._raw("/api/missions//activate", "POST", {})
        self.assertEqual(st, 404, body)

    def test_dispatching_with_no_id_is_404(self):
        st, body = self._raw("/api/jobs//dispatch", "POST", {})
        self.assertEqual(st, 404, body)

    def test_deleting_a_project_with_no_id_is_404(self):
        st, body = self._raw("/api/projects/", "DELETE")
        self.assertEqual(st, 404, body)

    def test_job_evidence_with_no_id_is_404(self):
        st, body = self._raw("/api/jobs//evidence")
        self.assertEqual(st, 404, body)

    def test_a_404_body_never_says_internal(self):
        # the whole point of the fix: the caller learns what went wrong
        for path in ("/api/missions/", "/api/jobs/", "/api/approvals/"):
            st, body = self._raw(path)
            self.assertNotIn("internal", body, f"{path} -> {body}")
            self.assertNotIn("Traceback", body, f"{path} -> {body}")

    def test_a_well_formed_but_unknown_id_is_still_404(self):
        # the case that already worked; it must keep working
        for path in ("/api/missions/mission_absent",
                     "/api/jobs/job_absent",
                     "/api/approvals/approval_absent"):
            st, body = self._raw(path)
            self.assertEqual(st, 404, f"{path} -> {body}")

    def test_activating_an_absent_mission_is_404(self):
        st, body = self._raw("/api/missions/mission_absent/activate", "POST", {})
        self.assertEqual(st, 404, body)

    def test_the_normal_routes_still_work(self):
        # a fix that 404s everything would also pass every test above
        for path in ("/api/status", "/api/missions", "/api/jobs",
                     "/api/approvals", "/api/projects", "/api/tools/registry",
                     "/api/events"):
            st, body = self._raw(path)
            self.assertEqual(st, 200, f"{path} -> {body[:80]}")

    # -- 2. no event is written for a mission that does not exist -------
    #
    # These two live in their own class on purpose. Mutation M3 (the existence
    # check moved back after the writes) is caught by each of them when run in
    # isolation, but NOT inside the shared server: an earlier test in the class
    # activates a real mission, so the feed already contains an entry and the
    # assertion cannot attribute the one the mutant added. A test that only
    # fails when run alone is a test that quietly stops testing.


class NoWriteOnRefusalTest(unittest.TestCase):
    """Its own server, its own database, so nothing else can prime the feed.

    Extracted from MissingResourceIs404Test after mutation M3 survived there:
    both tests below fail when run alone and pass inside the shared class,
    because an unrelated test had already written to the same event feed. A
    green result that depends on running order is not evidence.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f11nw-"))
        env = dict(os.environ, AGENT_OS_TOKEN=TOKEN)
        cls.proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "agent_os.cli", "serve",
             "--host", "127.0.0.1", "--port", PORT2,
             "--db", str(cls.tmp / "nw.db")],
            cwd=str(D), env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        cls.base = f"http://127.0.0.1:{PORT2}"
        end = time.time() + 40
        while time.time() < end:
            try:
                cls._raw("/api/status")
                return
            except Exception:
                time.sleep(0.25)
        raise AssertionError("server did not start")

    @classmethod
    def tearDownClass(cls):
        try:
            os.killpg(os.getpgid(cls.proc.pid), signal.SIGKILL)
            cls.proc.wait(timeout=10)
        except OSError:
            pass
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _raw(cls, path, method="GET", body=None):
        headers = {"Authorization": f"Bearer {TOKEN}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            cls.base + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_the_feed_is_empty_to_begin_with(self):
        # guards the guard: if this ever fails, every assertion below is void
        st, body = self._raw("/api/events")
        self.assertEqual(json.loads(body)["events"], [],
                         "this class needs a virgin feed")

    def test_the_refusal_is_a_404(self):
        st, body = self._raw("/api/missions/mission_absent/activate", "POST", {})
        self.assertEqual(st, 404, body)

    def test_activating_an_absent_mission_writes_no_event(self):
        self._raw("/api/missions/mission_absent/activate", "POST", {})
        st, body = self._raw("/api/events")
        blob = json.dumps(json.loads(body)["events"])
        self.assertNotIn(
            "mission_absent", blob,
            "the feed names a mission that does not exist")

    def test_no_mission_row_was_created(self):
        self._raw("/api/missions/mission_absent/activate", "POST", {})
        st, body = self._raw("/api/missions")
        ids = [m["id"] for m in json.loads(body)["missions"]]
        self.assertNotIn("mission_absent", ids)

    def test_the_service_layer_raises_before_any_write(self):
        from agent_os.service import ControlService
        from agent_os.store import Store
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="f11nwsvc-"))
        try:
            svc = ControlService(tmp / "s.db")
            with self.assertRaises(KeyError):
                svc.activate_mission("mission_absent")
            self.assertEqual(
                svc.store.list_events(), [],
                "the service wrote an event for a mission that does not exist")
            self.assertIsNone(svc.store.get_mission("mission_absent"))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class DiagnosticsShowsTheRequestTest(unittest.TestCase):
    """The captured status and path must reach the rendered line.

    Stored and never rendered is the exact failure being fixed, so the test
    reads the render expression rather than trusting that a field exists.
    """

    @classmethod
    def setUpClass(cls):
        cls.html = (D / "agent_os" / "web" / "index.html").read_text(
            encoding="utf-8")

    def test_the_render_line_includes_status_and_path(self):
        self.assertIn("r.status", self.html)
        self.assertIn("r.path", self.html,
                      "the render line never uses the captured path")

    def test_the_warning_records_the_path_it_came_from(self):
        i = self.html.find('"response body was not JSON"')
        self.assertNotEqual(i, -1)
        window = self.html[i:i + 200]
        self.assertIn("path:", window, "the warning does not name the request")

    def test_discover_is_guarded_by_a_token_check(self):
        i = self.html.find("async function runDiscovery()")
        self.assertNotEqual(i, -1)
        body = self.html[i:i + 700]
        self.assertIn("if (!TOKEN)", body,
                      "Discover still issues an unauthenticated request")

    def test_the_new_catalog_key_exists_in_both_languages(self):
        # three occurrences: the en entry, the fa entry, and the t() call site
        self.assertEqual(self.html.count('"ui.toolsNeedToken"'), 3)
        self.assertIn("t(\"ui.toolsNeedToken\")", self.html)
        # the two catalog entries must not be the same string
        import re
        vals = re.findall(r'"ui.toolsNeedToken":\s*"([^"]*)"', self.html)
        self.assertEqual(len(vals), 2, vals)
        self.assertNotEqual(vals[0], vals[1], "one language, not two")


if __name__ == "__main__":
    unittest.main(verbosity=2)
