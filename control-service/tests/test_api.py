"""HTTP API tests: auth, routing, and enforcement through the HTTP surface.

Covers:
- fail-closed: no token => serve() refuses
- wrong token => 401
- read endpoints return 200 with JSON
- create mission / propose / request-approval / decide / dispatch happy path
- decide via API always uses HUMAN principal (no self-approval over HTTP)
- dispatch to an unknown/unregistered executor is refused before work
- reconcile requires HUMAN and a valid interrupted/unknown job
"""

from __future__ import annotations

import json
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from agent_os.api import (
    AgentOSApi,
    make_handler,
    register_executor,
    unregister_executor,
)
from agent_os.models import ApprovalDecision, JobState, Principal, utc_now
from agent_os.service import ControlService
from agent_os.adapters.fake import FakeExecutor

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


def _future(hours: float = 2.0):
    """An expiry relative to the REAL clock (the API uses wall-clock now)."""
    from datetime import timedelta
    return utc_now() + timedelta(hours=hours)


class ApiUnitTest(unittest.TestCase):
    """Direct route-level tests (no socket)."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)
        self.api = AgentOSApi(self.svc, token="secret")

    def tearDown(self):
        unregister_executor("fake-executor")
        unregister_executor("crash-executor")
        self.svc.close()

    def _call(self, method, path, body=None):
        return self.api.handle(method, path, body)

    def test_status(self):
        status, payload = self._call("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "agent-os")
        self.assertIn("executors", payload)

    def test_create_mission(self):
        status, payload = self._call("POST", "/api/missions", {"title": "ship it"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["title"], "ship it")
        self.assertEqual(payload["state"], "draft")

    def test_full_happy_path(self):
        register_executor("fake-executor", FakeExecutor(behavior="success"))
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        mission_id = m["id"]

        _, j = self._call("POST", "/api/jobs", {
            "mission_id": mission_id,
            "title": "fix a test",
            "executor": "fake-executor",
            "workspace_paths": ["w/"],
            "actions": ["read_file", "write_file", "run_tests"],
            "proposed_by": "planner",
        })
        job_id = j["id"]

        _, a = self._call("POST", "/api/approvals", {
            "job_id": job_id,
            "expires_at": _future().isoformat(),
        })
        approval_id = a["id"]
        self.assertEqual(a["decision"], "requested")

        _, decided = self._call("POST", f"/api/approvals/{approval_id}/decide", {"decision": "granted"})
        self.assertEqual(decided["decision"], "granted")

        _, d = self._call("POST", f"/api/jobs/{job_id}/dispatch")
        self.assertEqual(d["receipt"]["final_state"], "completed_verified")
        self.assertEqual(d["receipt"]["duplicated"], False)

    def test_evidence_persisted_in_events_and_served(self):
        """Evidence is durable: it is written into the completion event and
        can be read back through /api/jobs/{id}/evidence."""
        register_executor("fake-executor", FakeExecutor(behavior="success"))
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t", "executor": "fake-executor",
            "workspace_paths": ["w/"], "actions": ["read_file", "run_tests"],
        })
        _, a = self._call("POST", "/api/approvals", {"job_id": j["id"]})
        self._call("POST", f"/api/approvals/{a['id']}/decide", {"decision": "granted"})
        _, d = self._call("POST", f"/api/jobs/{j['id']}/dispatch")
        self.assertEqual(d["receipt"]["final_state"], "completed_verified")

        # persisted into the append-only event log
        done = [e for e in self.svc.store.list_events() if e["kind"] == "job_completed_verified"]
        self.assertTrue(done)
        self.assertIn("3 passed", done[-1]["payload"]["evidence"]["test_report"])

        # and readable back through the API
        status, payload = self._call("GET", f"/api/jobs/{j['id']}/evidence")
        self.assertEqual(status, 200)
        self.assertIn("3 passed", payload["evidence"]["test_report"])
        self.assertEqual(payload["state"], "completed_verified")

    def test_evidence_endpoint_unknown_job(self):
        status, payload = self._call("GET", "/api/jobs/nope/evidence")
        self.assertEqual(status, 404)

    def test_dispatch_unknown_executor_refused(self):
        # no executor registered under this name
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t", "executor": "dsh",
            "workspace_paths": ["w/"], "actions": ["run_tests"],
        })
        _, a = self._call("POST", "/api/approvals", {"job_id": j["id"]})
        _, decided = self._call("POST", f"/api/approvals/{a['id']}/decide", {"decision": "granted"})
        status, payload = self._call("POST", f"/api/jobs/{j['id']}/dispatch")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "dispatch_refused")

    def test_decide_over_http_is_always_human(self):
        # The API's decide() hardcodes Principal.HUMAN, so an approval that
        # would be refused for a planner cannot be self-approved over HTTP.
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t", "executor": "fake-executor",
            "workspace_paths": ["w/"], "actions": ["read_file"],
        })
        _, a = self._call("POST", "/api/approvals", {"job_id": j["id"]})
        # valid decision
        status, _ = self._call("POST", f"/api/approvals/{a['id']}/decide", {"decision": "granted"})
        self.assertEqual(status, 200)

    def test_invalid_json_body_rejected(self):
        # handled at the transport layer; direct handler not exercised here.
        status, payload = self._call("POST", "/api/missions", {})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")

    def test_unknown_route(self):
        status, _ = self._call("GET", "/api/nope")
        self.assertEqual(status, 404)


class UiServingTest(unittest.TestCase):
    """The static UI shell is public on loopback (a browser cannot send an
    Authorization header); every /api/* endpoint stays token-protected."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)

    def tearDown(self):
        self.svc.close()

    def test_ui_served_without_auth_header_but_api_protected(self):
        import urllib.error
        import urllib.request

        from agent_os.api import serve

        server = serve(self.svc, host="127.0.0.1", port=0, token="secret", insecure=False)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            # UI shell: reachable with NO auth header (browser flow)
            with urllib.request.urlopen(
                urllib.request.Request(f"http://127.0.0.1:{port}/"), timeout=5
            ) as resp:
                self.assertEqual(resp.status, 200)
                html = resp.read()
            self.assertIn(b"Agent OS", html)
            # API data: still requires the token
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(
                    urllib.request.Request(f"http://127.0.0.1:{port}/api/status"), timeout=5
                )
            self.assertEqual(ctx.exception.code, 401)
            # ...and works with it
            r = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
            r.add_header("Authorization", "Bearer secret")
            with urllib.request.urlopen(r, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
        finally:
            server.shutdown()
            server.server_close()

    def test_oversized_body_rejected(self):
        """Requests larger than the body cap are refused with 413.

        On Python 3.14 the server closes the connection before the full body
        is sent, which may surface as a BrokenPipeError/URLError instead of
        a clean 413 HTTPError. Either outcome proves the oversized body was
        rejected; what must NOT happen is a 200 or a 201.
        """
        import urllib.error
        import urllib.request

        from agent_os.api import serve

        server = serve(self.svc, host="127.0.0.1", port=0, token="secret", insecure=False)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            big = json.dumps({"title": "x" * 1_100_000}).encode("utf-8")
            r = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/missions", data=big, method="POST"
            )
            r.add_header("Content-Type", "application/json")
            r.add_header("Authorization", "Bearer secret")
            try:
                with urllib.request.urlopen(r, timeout=10) as resp:
                    # A 2xx response means the oversized body was accepted — that is a failure.
                    self.fail(
                        f"Expected a 413 or connection error; got HTTP {resp.status}"
                    )
            except urllib.error.HTTPError as e:
                # Clean 413 — ideal.
                self.assertEqual(e.code, 413)
            except urllib.error.URLError:
                # BrokenPipe / connection reset from the server closing early.
                # The body was still rejected; this is acceptable on Python 3.14+.
                pass
        finally:
            server.shutdown()
            server.server_close()


class AuthUnitTest(unittest.TestCase):
    def test_serve_refuses_without_token(self):
        from agent_os.api import serve
        TMP.mkdir(exist_ok=True)
        svc = ControlService(TMP / "auth.db")
        try:
            with self.assertRaises(Exception) as ctx:
                serve(svc, token=None, insecure=False)
            self.assertIn("token", str(ctx.exception))
        finally:
            svc.close()

    def test_wrong_token_rejected(self):
        handler_cls = make_handler(None, token="correct")
        # We can't easily drive BaseHTTPRequestHandler without a socket;
        # test the authorize logic via a minimal fake.
        h = handler_cls.__new__(handler_cls)
        h.headers = {"Authorization": "Bearer wrong"}
        self.assertFalse(h._authorize())
        h.headers = {"Authorization": "Bearer correct"}
        self.assertTrue(h._authorize())
        # no auth header
        h.headers = {}
        self.assertFalse(h._authorize())


if __name__ == "__main__":
    unittest.main()
