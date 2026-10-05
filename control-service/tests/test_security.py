"""Security and penetration tests for Agent-OS control service.

Covers all six threat areas from the threat model (threat_model.md):
  1. API access control (auth bypass, token validation)
  2. UI surface (no secret exposure via UI endpoints)
  3. Container/subprocess executor boundary (path traversal, escaping symlinks)
  4. HermesExecutor workspace isolation (source_workspace never touched)
  5. Secret non-leakage (API keys/tokens not in API responses or logs)
  6. Approval bypass (fail-closed gates, HUMAN-only decisions, no self-approval)

Acceptance criterion: every test must PASS. Any failure is a security defect.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agent_os.api import (
    AgentOSApi,
    make_handler,
    register_executor,
    serve,
    unregister_executor,
)
from agent_os.models import (
    ApprovalDecision,
    Job,
    JobState,
    Principal,
    encode_command,
    utc_now,
)
from agent_os.service import ControlService
from agent_os.adapters.fake import FakeExecutor

TMP = Path(__file__).resolve().parent.parent / ".testtmp" / "security"


def _future():
    from datetime import timedelta
    return utc_now() + timedelta(hours=1)


def _make_api_and_server(token="sec-token", insecure=False):
    TMP.mkdir(parents=True, exist_ok=True)
    import uuid
    db = TMP / f"sec-{uuid.uuid4().hex[:8]}.db"
    svc = ControlService(db)
    server = serve(svc, host="127.0.0.1", port=0, token=token, insecure=insecure)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return svc, server, port


def _get(port, path, token=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(port, path, body, token=None):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ─────────────────────────────────────────────────────────────────────────────
# Threat 1: API Access Control
# ─────────────────────────────────────────────────────────────────────────────

# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

class ApiAuthTest(unittest.TestCase):
    """API endpoints must enforce bearer token authentication (Threat 1)."""

    def setUp(self):
        self.svc, self.server, self.port = _make_api_and_server()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.svc.close()

    def test_no_token_returns_401(self):
        """Every /api/ endpoint must reject requests with no token."""
        status, payload = _get(self.port, "/api/status")
        self.assertEqual(status, 401, "Expected 401 with no token")
        self.assertEqual(payload["error"]["code"], "unauthorized")

    def test_wrong_token_returns_401(self):
        """A wrong bearer token must be rejected."""
        status, payload = _get(self.port, "/api/status", token="WRONG-TOKEN")
        self.assertEqual(status, 401, "Expected 401 with wrong token")

    def test_correct_token_returns_200(self):
        """A correct bearer token must grant access."""
        status, payload = _get(self.port, "/api/status", token="sec-token")
        self.assertEqual(status, 200)
        self.assertIn("name", payload)

    def test_partial_token_prefix_rejected(self):
        """Sending only a prefix of the token must not grant access."""
        status, _ = _get(self.port, "/api/status", token="sec-to")
        self.assertEqual(status, 401)

    def test_empty_bearer_rejected(self):
        """An empty bearer value must be rejected."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/status")
        req.add_header("Authorization", "Bearer ")
        try:
            with urllib.request.urlopen(req, timeout=5):
                self.fail("Expected 401 but got 200")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

    def test_post_without_token_rejected(self):
        """POST to /api/missions with no token is rejected before any state change."""
        status, _ = _post(self.port, "/api/missions", {"title": "sneaky"})
        self.assertEqual(status, 401)

    def test_server_bound_to_loopback_only(self):
        """Server socket address must be 127.0.0.1 (loopback), not 0.0.0.0."""
        host = self.server.server_address[0]
        self.assertEqual(host, "127.0.0.1",
                         f"Server must bind to loopback; bound to {host!r}")

    def test_path_traversal_route_rejected(self):
        """Path traversal in API routes must return 404."""
        status, _ = _get(self.port, "/api/projects/../../etc/passwd", token="sec-token")
        self.assertEqual(status, 404)

    def test_sql_injection_attempt_handled_safely(self):
        """SQL injection attempt in route parameters must return 404 cleanly."""
        status, _ = _get(self.port, "/api/missions/%27%20OR%201=1%20--", token="sec-token")
        self.assertEqual(status, 404)

    def test_malformed_json_returns_400(self):
        """Malformed JSON payload in POST request must return 400 Bad Request."""
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/missions",
            data=b"invalid json body {",
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer sec-token")
        try:
            with urllib.request.urlopen(req, timeout=5):
                self.fail("Expected 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)


# ─────────────────────────────────────────────────────────────────────────────
# Threat 2: UI Surface / Secret Exposure
# ─────────────────────────────────────────────────────────────────────────────

class UiSecurityTest(unittest.TestCase):
    """UI endpoints must not expose secrets or internal paths (Threat 2)."""

    def setUp(self):
        self.svc, self.server, self.port = _make_api_and_server()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.svc.close()

    def test_ui_root_accessible_without_token(self):
        """/ must be reachable without auth (browser flow cannot send bearer)."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
        except urllib.error.HTTPError as e:
            # 404 is acceptable when UI is not bundled; 401 is a security error
            self.assertNotEqual(e.code, 401, "UI root must not require auth; got 401")

    def test_api_status_does_not_leak_token(self):
        """/api/status must not return the bearer token in any response field."""
        status, payload = _get(self.port, "/api/status", token="sec-token")
        self.assertEqual(status, 200)
        body_text = json.dumps(payload)
        self.assertNotIn("sec-token", body_text,
                         "Bearer token must never appear in API responses")

    def test_api_status_does_not_expose_db_path_contents(self):
        """/api/status may expose db_path as metadata but must not read file contents."""
        status, payload = _get(self.port, "/api/status", token="sec-token")
        self.assertEqual(status, 200)
        # db_path is acceptable metadata (helps operators locate the file)
        # but must NOT be the file contents
        if "db_path" in payload:
            self.assertIsInstance(payload["db_path"], str)
            # the value must be a path string, not file contents
            self.assertNotIn("\x00", payload["db_path"])
            self.assertLess(len(payload["db_path"]), 500,
                            "db_path value is suspiciously long; might be file contents")

    def test_ui_response_has_nosniff_header(self):
        """UI response must include X-Content-Type-Options: nosniff."""
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                self.fail(f"Unexpected error: {e}")

    def test_500_response_never_leaks_stack_trace(self):
        """Internal errors must return generic message, not a full traceback."""
        # We cannot easily induce a 500 via the public API without side effects,
        # so we test the AgentOSApi.handle directly with a mocked service that raises.
        TMP.mkdir(parents=True, exist_ok=True)
        import uuid
        db = TMP / f"err-{uuid.uuid4().hex[:8]}.db"
        svc = ControlService(db)
        try:
            api = AgentOSApi(svc, token="t")

            class _BadService:
                store = svc.store
                def get_mission(self, *a):
                    raise RuntimeError("internal db exploded with traceback detail")

            api.service = _BadService()
            status, payload = api.handle("GET", "/api/missions/fake-id", None)
            # Either 404 (normal) or 500 (error caught). Either is fine;
            # what matters is the response body must NOT contain the raw exception message.
            body_text = json.dumps(payload)
            self.assertNotIn("internal db exploded with traceback detail", body_text,
                             "Raw exception message must not appear in API responses")
        finally:
            svc.close()
            if db.exists():
                db.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# Threat 3: Container/Subprocess Executor Boundary
# ─────────────────────────────────────────────────────────────────────────────

class SubprocessExecutorSecurityTest(unittest.TestCase):
    """Subprocess executor must not escape source_workspace (Threat 3)."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="agent-os-sec-test-"))
        self.src = self.tmpdir / "workspace"
        self.src.mkdir()
        (self.src / "marker.txt").write_text("original")
        self.sandbox_root = self.tmpdir / "sandbox"
        self.sandbox_root.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _executor(self):
        from agent_os.adapters.subprocess_executor import SubprocessExecutor
        return SubprocessExecutor(self.src, sandbox_root=self.sandbox_root, timeout_seconds=10)

    def _make_job(self, command):
        return Job(
            id="sec-job-sub",
            mission_id="m",
            title="security test",
            proposed_by=Principal.PLANNER,
            executor="subprocess-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            state=JobState.APPROVED,
            attempt_no=0,
            manifest_hash="h",
            created_at="t",
            updated_at="t",
            command=encode_command(command),
        )

    def test_source_workspace_not_modified_after_run(self):
        """No file must be written into source_workspace by the executor."""
        job = self._make_job([sys.executable, "-c", "print('1 passed')"])
        self._executor().run(job, 1)
        contents = sorted(p.name for p in self.src.iterdir())
        self.assertEqual(contents, ["marker.txt"],
                         f"source_workspace must only contain marker.txt, found: {contents}")

    def test_escape_via_symlink_is_refused(self):
        """A symlink in source_workspace pointing outside must be refused, not followed."""
        from agent_os.adapters.subprocess_executor import SubprocessExecutor
        from agent_os.models import WorkerLostError

        outside = self.tmpdir / "outside.txt"
        outside.write_text("sensitive data outside workspace")
        link = self.src / "escape_link"
        link.symlink_to(outside)

        executor = SubprocessExecutor(self.src, sandbox_root=self.sandbox_root, timeout_seconds=10)
        job = self._make_job([sys.executable, "-c", "print('1 passed')"])
        with self.assertRaises(WorkerLostError) as ctx:
            executor.run(job, 1)
        # Error message must mention that it refused due to symlinks pointing outside
        err_msg = str(ctx.exception).lower()
        self.assertTrue(
            "symlink" in err_msg or "escaping" in err_msg or "outside" in err_msg,
            f"WorkerLostError must mention symlink escaping; got: {ctx.exception}"
        )

    def test_path_traversal_command_confined_to_sandbox(self):
        """A command that tries to write to ../ must fail or write inside sandbox only."""
        # The command tries to create a file one level up from sandbox cwd.
        # It will either fail (PermissionError / FileNotFoundError) or write to
        # its own sandbox copy — never to source_workspace or tmpdir root.
        job = self._make_job([
            sys.executable, "-c",
            "import os; open('../traversal_escape.txt', 'w').write('pwned')"
        ])
        self._executor().run(job, 1)
        # The escape file must NOT exist at the source workspace level
        escape_path = self.src / ".." / "traversal_escape.txt"
        self.assertFalse(
            escape_path.resolve().exists(),
            "Path traversal write must not escape the sandbox into source_workspace parent"
        )

    def test_sandbox_is_cleaned_up_after_run(self):
        """Sandbox copies must be removed after a successful run."""
        job = self._make_job([sys.executable, "-c", "print('1 passed')"])
        self._executor().run(job, 1)
        # sandbox_root must be empty (the run directory is cleaned up)
        leftover = list(self.sandbox_root.iterdir())
        self.assertEqual(leftover, [],
                         f"Sandbox run dirs must be cleaned up, found: {leftover}")

    def test_oversized_body_refused_at_transport(self):
        """The HTTP handler must refuse requests larger than MAX_BODY with 413."""
        svc, server, port = _make_api_and_server()
        try:
            big = json.dumps({"title": "x" * 1_100_000}).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/missions", data=big, method="POST"
            )
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", "Bearer sec-token")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(ctx.exception.code, 413)
        finally:
            server.shutdown()
            server.server_close()
            svc.close()


# ─────────────────────────────────────────────────────────────────────────────
# Threat 4: HermesExecutor Workspace Isolation
# ─────────────────────────────────────────────────────────────────────────────

class HermesExecutorWorkspaceIsolationTest(unittest.TestCase):
    """HermesExecutor must never write to source_workspace (Threat 4)."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="agent-os-hermes-sec-"))
        self.src = self.tmpdir / "workspace"
        self.src.mkdir()
        (self.src / "marker.txt").write_text("original")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_job(self, prompt="summarize this"):
        return Job(
            id="sec-job-hermes",
            mission_id="m",
            title="hermes security test",
            proposed_by=Principal.PLANNER,
            executor="hermes-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            state=JobState.APPROVED,
            attempt_no=0,
            manifest_hash="h",
            created_at="t",
            updated_at="t",
            command=encode_command(["solve", prompt]),
        )

    def test_source_workspace_not_modified_when_hermes_binary_missing(self):
        """Even when hermes binary is missing (no-op run), no artifact lands in source_workspace."""
        from agent_os.adapters.hermes_executor import HermesExecutor

        # Pass hermes_binary=None explicitly so the executor hits the early-return
        # branch for "binary not found" rather than raising FileNotFoundError.
        executor = HermesExecutor(self.src, hermes_binary=None)
        # Also patch _find_hermes to not accidentally find a real binary
        executor.hermes_binary = None
        job = self._make_job()
        executor.run(job, 1)

        contents = sorted(p.name for p in self.src.iterdir())
        self.assertEqual(contents, ["marker.txt"],
                         f"source_workspace must be clean after hermes run; found: {contents}")

    def test_no_usage_json_left_in_source_workspace(self):
        """The usage JSON file must NOT be written to source_workspace (fixed bug)."""
        from agent_os.adapters.hermes_executor import HermesExecutor

        # Any run (even a failed one) must not leave a .agent-os-usage-*.json
        # in source_workspace. This was a real bug that this test pins.
        executor = HermesExecutor(self.src, hermes_binary=None)
        executor.hermes_binary = None
        job = self._make_job()
        executor.run(job, 1)

        usage_files = list(self.src.glob(".agent-os-usage-*.json"))
        self.assertEqual(usage_files, [],
                         f"HermesExecutor must not write usage files in source_workspace; "
                         f"found: {usage_files}")

    def test_usage_tmpdir_not_in_source_workspace(self):
        """No temp directory created by HermesExecutor must live inside source_workspace."""
        from agent_os.adapters.hermes_executor import HermesExecutor

        executor = HermesExecutor(self.src, hermes_binary=None)
        executor.hermes_binary = None
        job = self._make_job()
        executor.run(job, 1)

        # After the run, nothing new must be inside source_workspace
        remaining = [p for p in self.src.iterdir() if p.name != "marker.txt"]
        self.assertEqual(remaining, [],
                         f"No artifacts may remain in source_workspace: {remaining}")


# ─────────────────────────────────────────────────────────────────────────────
# Threat 5: Secret non-leakage
# ─────────────────────────────────────────────────────────────────────────────

class SecretLeakageTest(unittest.TestCase):
    """No secret (env vars, tokens, file contents) must appear in API responses (Threat 5)."""

    def setUp(self):
        self.svc, self.server, self.port = _make_api_and_server(token="super-secret-42")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.svc.close()

    def test_env_vars_not_in_status(self):
        """OS environment variables must not be exposed via /api/status."""
        # We inject a canary env var and check it does not appear in any response
        canary = "AGENT_OS_CANARY_SECRET_12345"
        os.environ[canary] = "leaked_value_check"
        try:
            status, payload = _get(self.port, "/api/status", token="super-secret-42")
            self.assertEqual(status, 200)
            body_text = json.dumps(payload)
            self.assertNotIn("leaked_value_check", body_text,
                             "Environment variable values must not appear in API responses")
            self.assertNotIn(canary, body_text,
                             "Environment variable names must not appear in API responses")
        finally:
            del os.environ[canary]

    def test_token_not_echoed_in_error_body(self):
        """A 401 response must never echo the provided token back."""
        wrong = "wrong-super-secret-42"
        status, payload = _get(self.port, "/api/status", token=wrong)
        self.assertEqual(status, 401)
        body_text = json.dumps(payload)
        self.assertNotIn(wrong, body_text,
                         "Rejected token must not be echoed in the 401 response body")

    def test_mission_title_is_not_a_secret_leak_vector(self):
        """A mission title created with a secret string must only be
        accessible via authenticated endpoints, not via the UI shell."""
        canary_title = "CANARY-SECRET-MISSION-XYZ789"
        status, m = _post(self.port, "/api/missions",
                          {"title": canary_title}, token="super-secret-42")
        self.assertEqual(status, 201)

        # The UI shell (/) is public (no token needed). It must NOT contain
        # API data because the shell is static HTML only.
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            self.assertNotIn(canary_title, html,
                             "Static UI shell must not embed any API data or mission titles")
        except urllib.error.HTTPError:
            pass  # 404 when UI not bundled - that is acceptable


# ─────────────────────────────────────────────────────────────────────────────
# Threat 6: Approval Bypass / Fail-Closed Gates
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalBypassTest(unittest.TestCase):
    """Approval gates must be fail-closed; agents may not self-approve (Threat 6)."""

    def setUp(self):
        TMP.mkdir(parents=True, exist_ok=True)
        import uuid
        self.db = TMP / f"appr-{uuid.uuid4().hex[:8]}.db"
        self.svc = ControlService(self.db)
        self.api = AgentOSApi(self.svc, token="tok")
        register_executor("fake-exec", FakeExecutor(behavior="success"))

    def tearDown(self):
        unregister_executor("fake-exec")
        self.svc.close()
        if self.db.exists():
            self.db.unlink()

    def _call(self, method, path, body=None):
        return self.api.handle(method, path, body)

    def test_dispatch_without_approval_rejected(self):
        """A job with no approval must not be dispatched (fail-closed)."""
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t",
            "executor": "fake-exec",
            "workspace_paths": ["w/"], "actions": ["run_tests"],
        })
        # Attempt dispatch WITHOUT creating an approval
        status, payload = self._call("POST", f"/api/jobs/{j['id']}/dispatch")
        # Must not succeed; job requires an approval first
        self.assertNotEqual(status, 200,
                            "Dispatch without approval must not return 200")
        if status == 409:
            self.assertIn("dispatch_refused", payload.get("error", {}).get("code", ""))

    def test_dispatch_with_requested_not_granted_approval_rejected(self):
        """An approval in 'requested' state (not yet decided) must block dispatch."""
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t",
            "executor": "fake-exec",
            "workspace_paths": ["w/"], "actions": ["run_tests"],
        })
        # Create approval but do NOT decide it
        _, a = self._call("POST", "/api/approvals", {"job_id": j["id"]})
        self.assertEqual(a["decision"], "requested")

        status, payload = self._call("POST", f"/api/jobs/{j['id']}/dispatch")
        self.assertNotEqual(status, 200,
                            "Dispatch with undecided approval must not succeed")

    def test_dispatch_with_denied_approval_rejected(self):
        """An explicitly denied approval must block dispatch."""
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t",
            "executor": "fake-exec",
            "workspace_paths": ["w/"], "actions": ["run_tests"],
        })
        _, a = self._call("POST", "/api/approvals", {"job_id": j["id"]})
        # Human explicitly denies
        _, decided = self._call("POST", f"/api/approvals/{a['id']}/decide",
                                {"decision": "denied"})
        self.assertEqual(decided["decision"], "denied")

        status, payload = self._call("POST", f"/api/jobs/{j['id']}/dispatch")
        self.assertNotEqual(status, 200,
                            "Dispatch with denied approval must not succeed")

    def test_decide_endpoint_hardcoded_to_human_principal(self):
        """The /api/approvals/{id}/decide endpoint must record the decision as HUMAN.

        An agent cannot self-approve by claiming a different principal through
        the API — the handler always sets Principal.HUMAN regardless of request body.
        """
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t",
            "executor": "fake-exec",
            "workspace_paths": ["w/"], "actions": ["run_tests"],
        })
        _, a = self._call("POST", "/api/approvals", {"job_id": j["id"]})
        _, decided = self._call("POST", f"/api/approvals/{a['id']}/decide",
                                {"decision": "granted"})
        self.assertEqual(decided["decision"], "granted")
        self.assertEqual(decided["decided_by"], Principal.HUMAN.value,
                         "Approval decision must always be recorded as HUMAN")

    def test_full_grant_then_dispatch_succeeds(self):
        """A properly granted approval must allow dispatch (positive control)."""
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t",
            "executor": "fake-exec",
            "workspace_paths": ["w/"], "actions": ["run_tests"],
        })
        _, a = self._call("POST", "/api/approvals", {"job_id": j["id"]})
        self._call("POST", f"/api/approvals/{a['id']}/decide", {"decision": "granted"})
        status, payload = self._call("POST", f"/api/jobs/{j['id']}/dispatch")
        self.assertEqual(status, 200, f"Properly approved job must dispatch: {payload}")
        self.assertEqual(payload["receipt"]["final_state"], "completed_verified")

    def test_serve_refuses_to_start_without_token(self):
        """serve() must refuse to bind when no token is set and insecure=False (fail-closed)."""
        TMP.mkdir(parents=True, exist_ok=True)
        import uuid
        db = TMP / f"notok-{uuid.uuid4().hex[:8]}.db"
        svc = ControlService(db)
        try:
            with self.assertRaises(Exception) as ctx:
                serve(svc, token=None, insecure=False)
            self.assertIn("token", str(ctx.exception).lower(),
                          "Error must mention 'token'")
        finally:
            svc.close()
            if db.exists():
                db.unlink()

    def test_unknown_executor_dispatch_refused(self):
        """Dispatch to an unregistered executor must be refused (registry is the only surface)."""
        _, m = self._call("POST", "/api/missions", {"title": "m"})
        _, j = self._call("POST", "/api/jobs", {
            "mission_id": m["id"], "title": "t",
            "executor": "unregistered-rce-vector",
            "workspace_paths": ["w/"], "actions": ["run_tests"],
        })
        _, a = self._call("POST", "/api/approvals", {"job_id": j["id"]})
        self._call("POST", f"/api/approvals/{a['id']}/decide", {"decision": "granted"})
        status, payload = self._call("POST", f"/api/jobs/{j['id']}/dispatch")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "dispatch_refused")


if __name__ == "__main__":
    unittest.main()
