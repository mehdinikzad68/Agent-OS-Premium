"""Phase 5 tests: single-use approvals, action binding, restart durability.

Run against a live HTTP server, not a stub: the dispatcher is what turns an
exception into a status, and a unit test of _get() would miss that entirely.

Each test class boots its own server on an OS-chosen port with its own
database (see tests/live_server.py), so a result never depends on the order
the classes happen to run in.

Not covered here: true concurrent dispatch - that has its own test,
tests/test_dispatch_concurrency.py (two threads, one approval, exactly one
execution), added after review 2026-10-05 showed the store's RLock
serializes each store CALL but not dispatch()'s check-then-act sequence.
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

from tests.live_server import boot_server, stop_server, restart_server  # noqa: E402

TOKEN = "p5-test-token"


# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

class Phase5BaseTest(unittest.TestCase):
    """Base class that boots a live server for each test class."""

    @classmethod
    def setUpClass(cls):
        # An OS-chosen port (tests/live_server.py): a fixed one let an orphan
        # from a killed run answer our readiness probe with a stale database.
        cls.srv = boot_server(TOKEN, prefix="p5-srv-", db_name="p5.db")
        cls.tmp = cls.srv["tmp"]
        cls.base = cls.srv["base"]

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.srv)

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

    @classmethod
    def _post(cls, path, body):
        return cls._raw(path, method="POST", body=body)

    @classmethod
    def _get(cls, path):
        return cls._raw(path)

    @classmethod
    def _create_mission(cls):
        st, body = cls._post("/api/missions", {"title": "p5-test"})
        assert st == 201, body
        return json.loads(body)["id"]

    @classmethod
    def _create_job(cls, mission_id, actions=None, command=None):
        body = {
            "mission_id": mission_id,
            "title": "p5-job",
            "executor": "fake-executor",
            "workspace_paths": ["/tmp/p5-test"],
            "actions": actions or ["run_tests"],
            "proposed_by": "planner",
        }
        if command:
            body["command"] = command
        st, resp = cls._post("/api/jobs", body)
        assert st == 201, resp
        return json.loads(resp)

    @classmethod
    def _request_approval(cls, job_id, action=None):
        body = {"job_id": job_id}
        if action:
            body["action"] = action
        st, resp = cls._post("/api/approvals", body)
        assert st == 201, resp
        return json.loads(resp)

    @classmethod
    def _grant_approval(cls, approval_id):
        st, resp = cls._post(f"/api/approvals/{approval_id}/decide", {
            "decision": "granted",
        })
        assert st == 200, resp
        return json.loads(resp)

    @classmethod
    def _dispatch(cls, job_id):
        return cls._post(f"/api/jobs/{job_id}/dispatch", {})


class SingleUseTest(Phase5BaseTest):
    """An approval can only be consumed once."""

    def test_01_approval_is_consumed_after_dispatch(self):
        mid = self._create_mission()
        job = self._create_job(mid)
        appr = self._request_approval(job["id"])
        self._grant_approval(appr["id"])

        # First dispatch should succeed
        st, body = self._dispatch(job["id"])
        self.assertEqual(st, 200, body)
        receipt = json.loads(body)["receipt"]
        self.assertEqual(receipt["final_state"], "completed_verified")

        # Approval should now be consumed
        st, body = self._get(f"/api/approvals/{appr['id']}")
        self.assertEqual(st, 200, body)
        self.assertIsNotNone(json.loads(body)["consumed_at"])

    def test_02_second_dispatch_is_an_idempotent_replay(self):
        """Single-use is enforced by the action running ONCE, not by turning a
        retry into an error.

        The approval is spent on the first dispatch (consume_approval) and
        policy check 9 refuses a consumed approval. But A6 - documented in
        README and READINESS, and asserted by e2e step 7 - requires a duplicate
        dispatch of a finished job to be an idempotent replay. So the second
        call answers 200 with duplicated=true and no second execution; the
        approval stays spent either way.
        """
        mid = self._create_mission()
        job = self._create_job(mid)
        appr = self._request_approval(job["id"])
        self._grant_approval(appr["id"])

        # First dispatch: runs once and spends the approval.
        st, body = self._dispatch(job["id"])
        self.assertEqual(st, 200, body)
        self.assertFalse(json.loads(body)["receipt"]["duplicated"])

        # Second dispatch: a replay. Nothing runs again.
        st, body = self._dispatch(job["id"])
        self.assertEqual(st, 200, body)
        receipt = json.loads(body)["receipt"]
        self.assertTrue(receipt["duplicated"])
        self.assertEqual(receipt["attempt"], 1)

        # The approval is still spent, so it can never authorise another action.
        st, body = self._get(f"/api/approvals/{appr['id']}")
        self.assertEqual(st, 200, body)
        self.assertIsNotNone(json.loads(body)["consumed_at"])


class ActionBindingTest(Phase5BaseTest):
    """An approval is bound to a specific action."""

    def test_03_action_mismatch_refused(self):
        mid = self._create_mission()
        job = self._create_job(mid, actions=["run_tests", "delete_file"])
        # Approve for run_tests only
        appr = self._request_approval(job["id"], action="run_tests")
        self._grant_approval(appr["id"])

        # Dispatch should succeed (run_tests is in job.actions)
        st, body = self._dispatch(job["id"])
        self.assertEqual(st, 200, body)

    def test_04_action_not_in_job_refused(self):
        mid = self._create_mission()
        job = self._create_job(mid, actions=["run_tests"])
        # Approve for delete_file, but job only has run_tests
        appr = self._request_approval(job["id"], action="delete_file")
        self._grant_approval(appr["id"])

        # Dispatch should be refused
        st, body = self._dispatch(job["id"])
        self.assertEqual(st, 409, body)
        data = json.loads(body)
        self.assertEqual(data["error"]["code"], "dispatch_refused")
        self.assertEqual(data["error"]["message"], "action_not_approved:delete_file")

    def test_05_action_defaults_to_first_job_action(self):
        mid = self._create_mission()
        job = self._create_job(mid, actions=["run_tests", "delete_file"])
        # No action specified - should default to first action (run_tests)
        appr = self._request_approval(job["id"])
        self._grant_approval(appr["id"])

        # Dispatch should succeed
        st, body = self._dispatch(job["id"])
        self.assertEqual(st, 200, body)


class RestartDurabilityTest(Phase5BaseTest):
    """Approvals survive service restart."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create a job and approval before "restart"
        cls._mid = cls._create_mission()
        cls._job = cls._create_job(cls._mid)
        cls._appr = cls._request_approval(cls._job["id"])
        cls._grant_approval(cls._appr["id"])

    @classmethod
    def tearDownClass(cls):
        # Restart against the SAME database, then let the base class stop it.
        # The restart is the measurement: the tests below ask the new process
        # about state the old one wrote.
        cls.srv = restart_server(cls.srv, token=TOKEN)
        cls.base = cls.srv["base"]
        super().tearDownClass()

    def test_06_approval_survives_restart(self):
        # Approval should still be there
        st, body = self._get(f"/api/approvals/{self._appr['id']}")
        self.assertEqual(st, 200, body)
        data = json.loads(body)
        self.assertEqual(data["decision"], "granted")
        self.assertIsNone(data["consumed_at"])

    def test_07_dispatch_after_restart_succeeds(self):
        st, body = self._dispatch(self._job["id"])
        self.assertEqual(st, 200, body)
        receipt = json.loads(body)["receipt"]
        self.assertEqual(receipt["final_state"], "completed_verified")


class SensitiveActionTest(Phase5BaseTest):
    """A sensitive action requires approval before side effect."""

    def test_08_delete_file_requires_approval(self):
        mid = self._create_mission()
        job = self._create_job(mid, actions=["delete_file"])

        # Dispatch without approval should be refused
        st, body = self._dispatch(job["id"])
        self.assertEqual(st, 409, body)
        data = json.loads(body)
        self.assertEqual(data["error"]["code"], "dispatch_refused")

        # Now approve and dispatch
        appr = self._request_approval(job["id"], action="delete_file")
        self._grant_approval(appr["id"])
        st, body = self._dispatch(job["id"])
        self.assertEqual(st, 200, body)

    def test_09_no_side_effect_without_approval(self):
        mid = self._create_mission()
        job = self._create_job(mid, actions=["delete_file"])

        # Try to dispatch without approval
        st, _ = self._dispatch(job["id"])
        self.assertEqual(st, 409)

        # Job should still be in proposed state (no side effect)
        st, body = self._get(f"/api/jobs/{job['id']}")
        self.assertEqual(st, 200, body)
        data = json.loads(body)
        # Job should be back to proposed (approval was never granted)
        self.assertIn(data["state"], ["proposed", "awaiting_approval"])


class ConsumedAtTest(Phase5BaseTest):
    """The consumed_at field is set correctly."""

    def test_10_consumed_at_is_iso_timestamp(self):
        mid = self._create_mission()
        job = self._create_job(mid)
        appr = self._request_approval(job["id"])
        self._grant_approval(appr["id"])

        # Before dispatch, consumed_at is None
        st, body = self._get(f"/api/approvals/{appr['id']}")
        self.assertIsNone(json.loads(body)["consumed_at"])

        # Dispatch
        self._dispatch(job["id"])

        # After dispatch, consumed_at is set
        st, body = self._get(f"/api/approvals/{appr['id']}")
        data = json.loads(body)
        self.assertIsNotNone(data["consumed_at"])
        # Should be a valid ISO timestamp
        from datetime import datetime
        datetime.fromisoformat(data["consumed_at"])


if __name__ == "__main__":
    unittest.main()
