# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Tests for the external event ingestion API.

Same claims as the adapter tests, exercised over real HTTP against a real
server, because the status codes and the auth gate are part of what is being
claimed.

The properties that matter most, in order:

1. A replay adds nothing. The dedup key is the source's own row id, so
   ingesting the same range twice must not double the log - otherwise a
   reconnect silently rewrites history.
2. An unreadable source is `unavailable`, never a 200 with an empty list.
3. Ingesting grants no authority. The executor list, the registered tools and
   the tool registry are byte-for-byte unchanged by an ingest pass.
4. Every ingested payload says `observed_only`, and nothing in it claims to
   have blocked or prevented anything.
5. The path is authenticated like every other route.
"""
import json
import os
import pathlib
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

D = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(D))

from tests.live_server import boot_server, stop_server  # noqa: E402

TOKEN = "p4-api-token"


def build_source(path, sessions, messages):
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, model TEXT, "
        "git_repo_root TEXT, started_at REAL)")
    con.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
        "role TEXT, content TEXT, tool_name TEXT, tool_call_id TEXT, "
        "timestamp REAL)")
    con.executemany("INSERT INTO sessions VALUES (?,?,?,?,?)", sessions)
    con.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", messages)
    con.commit()
    con.close()


SESSIONS = [("s1", "desktop", "m1", "/repo", 100.0)]
MESSAGES = [
    (1, "s1", "user", "hi", None, None, 10.0),
    (2, "s1", "tool", "SECRET", "terminal", "c1", 11.0),
    (3, "s1", "tool", "SECRET", "write_file", "c2", 12.0),
    (4, "s1", "tool", "SECRET", None, "c3", 13.0),
]


# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

class IngestApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="p4api-"))
        cls.source = cls.tmp / "state.db"
        build_source(cls.source, SESSIONS, MESSAGES)
        # M1 (B2): ingest sources are allowlisted (AGENT_OS_INGEST_ROOTS);
        # every fixture in this class lives under cls.tmp. Set BEFORE boot
        # so the server subprocess inherits it.
        import os as _os
        cls._prev_roots = _os.environ.get("AGENT_OS_INGEST_ROOTS")
        _os.environ["AGENT_OS_INGEST_ROOTS"] = str(cls.tmp)
        # The port is the kernel's choice, not ours: see tests/live_server.py
        # for why a fixed port made this suite lie after a killed run.
        cls.srv = boot_server(TOKEN, prefix="p4api-srv-")
        cls.base = cls.srv["base"]

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.srv)
        import os as _os
        if getattr(cls, "_prev_roots", None) is None:
            _os.environ.pop("AGENT_OS_INGEST_ROOTS", None)
        else:
            _os.environ["AGENT_OS_INGEST_ROOTS"] = cls._prev_roots
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _raw(cls, method, path, body=None, token=TOKEN):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
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

    def _ingest(self, cursor=0, limit=500):
        return self._raw("POST", "/api/events/ingest",
                         {"source": str(self.source), "cursor": cursor,
                          "limit": limit})

    def _external(self):
        st, body = self._raw("GET", "/api/events/external")
        return st, json.loads(body)["events"]

    # -- 1. replay safety ------------------------------------------------

    def test_a_first_pass_adds_the_tool_rows(self):
        st, body = self._ingest()
        self.assertEqual(st, 200, body)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["added"], 3, body)
        self.assertEqual(data["cursor"], 4)

    def test_replaying_the_same_range_adds_nothing(self):
        before = len(self._external()[1])
        st, body = self._ingest()
        data = json.loads(body)
        self.assertEqual(data["added"], 0, body)
        self.assertEqual(data["skipped"], 3, body)
        self.assertEqual(len(self._external()[1]), before,
                         "a replay duplicated events")

    def test_rewinding_the_cursor_does_not_duplicate(self):
        st, body = self._ingest(cursor=0)
        self.assertEqual(json.loads(body)["added"], 0, body)
        self.assertEqual(len(self._external()[1]), 3)

    def test_a_source_outside_the_allowed_roots_is_403(self):
        """M1: an arbitrary local path must be refused, not read."""
        st, body = self._raw("POST", "/api/events/ingest",
                             {"source": "/etc/passwd"})
        self.assertEqual(st, 403, body)
        self.assertEqual(json.loads(body)["error"]["code"], "forbidden")

    # -- 2. unavailable is not empty ------------------------------------

    def test_an_unreadable_source_reports_unavailable(self):
        st, body = self._raw("POST", "/api/events/ingest",
                             {"source": str(self.tmp / "nope.db")})
        self.assertEqual(st, 200, body)
        data = json.loads(body)
        self.assertEqual(data["status"], "unavailable")
        self.assertEqual(data["added"], 0)
        self.assertTrue(data["reason"])

    def test_a_file_that_is_not_a_database_reports_unavailable(self):
        f = self.tmp / "plain.txt"
        f.write_text("not a database", encoding="utf-8")
        st, body = self._raw("POST", "/api/events/ingest", {"source": str(f)})
        self.assertEqual(json.loads(body)["status"], "unavailable", body)

    def test_a_source_with_nothing_new_is_ok_not_unavailable(self):
        st, body = self._raw("POST", "/api/events/ingest",
                             {"source": str(self.source), "cursor": 4})
        data = json.loads(body)
        self.assertEqual(data["status"], "ok", body)
        self.assertEqual(data["added"], 0)

    def test_a_missing_source_parameter_is_refused(self):
        st, body = self._raw("POST", "/api/events/ingest", {})
        self.assertEqual(st, 400, body)
        self.assertEqual(json.loads(body)["error"]["code"], "bad_request")

    # -- 3. ingesting grants nothing ------------------------------------

    def test_ingesting_leaves_the_executor_list_untouched(self):
        before = self._raw("GET", "/api/executors")[1]
        self._ingest(cursor=0)
        after = self._raw("GET", "/api/executors")[1]
        self.assertEqual(before, after)

    def test_ingesting_leaves_the_tool_registry_untouched(self):
        before = self._raw("GET", "/api/tools/registry")[1]
        self._ingest(cursor=0)
        after = self._raw("GET", "/api/tools/registry")[1]
        self.assertEqual(before, after)

    def test_ingesting_creates_no_mission_job_or_approval(self):
        for path, key in (("/api/missions", "missions"), ("/api/jobs", "jobs"),
                          ("/api/approvals", "approvals")):
            st, body = self._raw("GET", path)
            self.assertEqual(json.loads(body)[key], [], f"{path} -> {body}")

    # -- 4. the payload says what it is ---------------------------------

    def test_every_ingested_payload_is_marked_observed_only(self):
        st, events = self._external()
        self.assertTrue(events, "no events were ingested")
        for e in events:
            self.assertTrue(e["payload"]["observed_only"], e)

    def test_no_payload_claims_to_have_blocked_anything(self):
        st, events = self._external()
        blob = json.dumps(events).lower()
        for word in ("blocked", "denied", "prevented", "refused", "enforced",
                     "interrupted", "stopped"):
            self.assertNotIn(word, blob,
                             f"an ingested event claims it {word} something")

    def test_the_payload_carries_no_message_content(self):
        st, events = self._external()
        self.assertNotIn("SECRET", json.dumps(events))

    def test_the_unknown_tool_name_survives_into_the_log(self):
        st, events = self._external()
        names = [e["payload"]["tool_name"] for e in events]
        self.assertIn("unknown", names, names)
        row = [e for e in events if e["payload"]["tool_name"] == "unknown"][0]
        self.assertTrue(any("not attributable" in n
                            for n in row["payload"]["notes"]), row)

    def test_the_source_row_id_is_kept_for_correlation(self):
        st, events = self._external()
        ids = sorted(e["payload"]["source_row_id"] for e in events)
        self.assertEqual(ids, [2, 3, 4])
        sessions = {e["payload"]["session_id"] for e in events}
        self.assertEqual(sessions, {"s1"})

    # -- 5. the route is authenticated ----------------------------------

    def test_ingest_requires_a_token(self):
        st, body = self._raw("POST", "/api/events/ingest",
                             {"source": str(self.source)}, token=None)
        self.assertEqual(st, 401, body)

    def test_reading_external_events_requires_a_token(self):
        st, body = self._raw("GET", "/api/events/external", token=None)
        self.assertEqual(st, 401, body)

    def test_a_wrong_token_is_refused(self):
        st, body = self._raw("GET", "/api/events/external", token="nope")
        self.assertEqual(st, 401, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
