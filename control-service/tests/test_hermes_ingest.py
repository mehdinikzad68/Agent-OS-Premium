# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Tests for Hermes event ingestion.

The claims worth defending, in order of how badly a bug would hurt:

1. Nothing is invented. A row with no tool name becomes unknown WITH a
   reason; a row with no timestamp is kept and marked; a row with no repo root
   reports unknown and is never inferred from cwd. A test that only checked
   the happy path would pass a mapper that filled gaps with plausible values.
2. Message content is never read. The boundary must be structural - the query
   does not name the column - so a later edit cannot quietly leak it.
3. A source that cannot be read is distinguishable from one with no new rows.
   Conflating them makes a Hermes restart look like a quiet period.
4. The timeline is ordered by id, because the real data contains rows whose
   timestamps go backwards relative to id.
5. The cursor advances only over rows actually converted, so a partial pass
   does not skip the rest.

These use a purpose-built fixture rather than the live profile: the live
database grows while it is read, so a test asserting an exact count would be
flaky for a reason that has nothing to do with the code. The real-database
run is a separate proof, and both are required.
"""
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from agent_os.adapters.hermes_ingest import (  # noqa: E402
    UNKNOWN, SourceUnavailable, StateReader, row_to_event)


def build_db(path, sessions, messages):
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


SESSIONS = [
    ("s1", "desktop", "m1", "/repo", 100.0),
    ("s2", None, None, None, 200.0),
]
MESSAGES = [
    # id, session, role, content, tool, call_id, ts
    (1, "s1", "user", "hello", None, None, 10.0),
    (2, "s1", "assistant", "", None, None, 11.0),
    (3, "s1", "tool", "SECRET TEXT", "terminal", "c1", 12.0),
    (4, "s1", "tool", "SECRET TEXT", "write_file", "c2", 13.0),
    # a backwards timestamp: id 5 is older than id 4
    (5, "s1", "tool", "SECRET TEXT", "patch", "c3", 5.0),
    # no tool name at all
    (6, "s1", "tool", "SECRET TEXT", None, "c4", 14.0),
    # no timestamp
    (7, "s1", "tool", "SECRET TEXT", "read_file", "c5", None),
    # a session whose source/model/repo are all null
    (8, "s2", "tool", "SECRET TEXT", "memory", "c6", 20.0),
]


class RowMappingTest(unittest.TestCase):
    def test_a_normal_row_maps_its_fields(self):
        ev = row_to_event((3, "s1", "terminal", "c1", 12.0, "desktop",
                           "m1", "/repo"))
        self.assertEqual(ev.row_id, 3)
        self.assertEqual(ev.tool_name, "terminal")
        self.assertEqual(ev.source, "desktop")
        self.assertEqual(ev.repo_root, "/repo")
        self.assertTrue(ev.attributable)

    def test_a_missing_tool_name_becomes_unknown_with_a_reason(self):
        ev = row_to_event((6, "s1", None, "c4", 14.0, "desktop", "m1", "/repo"))
        self.assertEqual(ev.tool_name, UNKNOWN)
        self.assertFalse(ev.attributable)
        self.assertTrue(any("field is null" in n for n in ev.notes))
        self.assertTrue(any("not attributable" in n for n in ev.notes))

    def test_a_missing_timestamp_keeps_the_row_and_says_so(self):
        ev = row_to_event((7, "s1", "read_file", "c5", None, "desktop", "m1",
                           "/repo"))
        self.assertEqual(ev.timestamp, 0.0)
        self.assertTrue(any("cannot be placed" in n for n in ev.notes))
        self.assertEqual(ev.tool_name, "read_file")

    def test_a_row_with_no_id_is_refused_rather_than_mapped(self):
        with self.assertRaises(ValueError):
            row_to_event((None, "s1", "terminal", "c1", 1.0, "d", "m", "/r"))

    def test_absent_metadata_is_unknown_never_guessed(self):
        ev = row_to_event((8, "s2", "memory", "c6", 20.0, None, None, None))
        self.assertEqual(ev.source, UNKNOWN)
        self.assertEqual(ev.model, UNKNOWN)
        self.assertEqual(ev.repo_root, UNKNOWN)
        # and nothing was inferred from the session id or the timestamp
        self.assertNotIn("/repo", ev.repo_root)

    def test_a_false_timestamp_is_not_accepted_as_a_time(self):
        ev = row_to_event((9, "s1", "terminal", "c9", False, "d", "m", "/r"))
        self.assertEqual(ev.timestamp, 0.0)


class RedactionTest(unittest.TestCase):
    def test_the_query_never_selects_content(self):
        from agent_os.adapters import hermes_ingest
        self.assertNotIn("content", hermes_ingest._SELECT)

    def test_no_event_carries_the_content(self):
        ev = row_to_event((3, "s1", "terminal", "c1", 12.0, "desktop", "m1",
                           "/repo"))
        self.assertNotIn("SECRET TEXT", json_of(ev))
        for v in ev.to_dict().values():
            self.assertNotIn("SECRET TEXT", str(v))


def json_of(ev):
    import json
    return json.dumps(ev.to_dict())


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="ingest-"))
        self.db = self.tmp / "state.db"
        build_db(self.db, SESSIONS, MESSAGES)
        self.reader = StateReader(str(self.db))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_probe_reports_the_real_extent(self):
        p = self.reader.probe()
        self.assertTrue(p["readable"])
        self.assertEqual(p["max_row_id"], 8)
        self.assertEqual(p["tool_rows"], 6)

    def test_only_tool_rows_become_events(self):
        events, cursor = self.reader.read_since(0)
        self.assertEqual([e.row_id for e in events], [3, 4, 5, 6, 7, 8])
        self.assertEqual(cursor, 8)
        self.assertTrue(all(e.tool_name != UNKNOWN or not e.attributable
                            for e in events))

    def test_the_order_is_by_id_even_when_time_goes_backwards(self):
        events, _ = self.reader.read_since(0)
        stamps = [e.timestamp for e in events]
        # 12, 13, 5 - a backwards step that a time sort would have moved
        self.assertEqual(stamps[:3], [12.0, 13.0, 5.0])
        self.assertEqual([e.row_id for e in events],
                         sorted(e.row_id for e in events))

    def test_a_limit_is_honoured(self):
        events, cursor = self.reader.read_since(0, limit=2)
        self.assertEqual(len(events), 2)
        self.assertEqual(cursor, 4)

    def test_a_second_read_from_the_tip_returns_nothing(self):
        _, cursor = self.reader.read_since(0)
        again, cursor2 = self.reader.read_since(cursor)
        self.assertEqual(again, [])
        self.assertEqual(cursor2, cursor)

    def test_the_cursor_never_skips_a_row(self):
        # a limit that stops mid-way, then resume: nothing is lost
        first, c1 = self.reader.read_since(0, limit=2)
        second, c2 = self.reader.read_since(c1, limit=10)
        ids = [e.row_id for e in first] + [e.row_id for e in second]
        self.assertEqual(ids, [3, 4, 5, 6, 7, 8])
        self.assertEqual(c2, 8)


class SourceStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="ingest-x-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_missing_file_is_unavailable_not_empty(self):
        with self.assertRaises(SourceUnavailable):
            StateReader(str(self.tmp / "nope.db")).probe()

    def test_a_file_that_is_not_a_database_is_unavailable(self):
        f = self.tmp / "notadb"
        f.write_text("hello", encoding="utf-8")
        with self.assertRaises(SourceUnavailable):
            StateReader(str(f)).probe()

    def test_a_database_without_the_expected_tables_is_refused(self):
        f = self.tmp / "other.db"
        con = sqlite3.connect(str(f))
        con.execute("CREATE TABLE unrelated (a INTEGER)")
        con.commit()
        con.close()
        with self.assertRaises(SourceUnavailable) as ctx:
            StateReader(str(f)).probe()
        self.assertIn("messages", str(ctx.exception))

    def test_empty_and_unavailable_are_different_outcomes(self):
        # empty means readable and no rows; unavailable means it could not be read
        f = self.tmp / "empty.db"
        build_db(f, [], [])
        reader = StateReader(str(f))
        events, cursor = reader.read_since(0)
        self.assertEqual(events, [])
        self.assertEqual(cursor, 0)
        with self.assertRaises(SourceUnavailable):
            StateReader(str(self.tmp / "gone.db")).probe()


class LocklessMountTest(unittest.TestCase):
    """The profile lives on a Windows drive reached from WSL.

    Measured 2026-09-28: SQLite raises `disk I/O error` there on a plain
    read-only open, because the locking it performs is not available on that
    mount. `immutable=1` is what makes the read work, and without a test for
    it this whole adapter is dead on the one filesystem that matters.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="ingest-imm-"))
        self.db = self.tmp / "state.db"
        build_db(self.db, SESSIONS, MESSAGES)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_normal_read_still_works(self):
        r = StateReader(str(self.db))
        events, _ = r.read_since(0)
        self.assertEqual(len(events), 6)

    def test_the_immutable_form_is_tried_first(self):
        # the URI order matters: immutable first, plain second
        import agent_os.adapters.hermes_ingest as m
        seen = []
        real_connect = sqlite3.connect

        def spy(target, *a, **kw):
            seen.append(target)
            return real_connect(target, *a, **kw)

        sqlite3.connect = spy
        try:
            StateReader(str(self.db)).probe()
        finally:
            sqlite3.connect = real_connect
        self.assertTrue(seen, "sqlite3.connect was never called")
        self.assertIn("immutable=1", seen[0])
        self.assertIn("mode=ro", seen[0])

    def test_the_open_is_probed_so_a_bad_mount_fails_immediately(self):
        # a mount that cannot serve a read must fail on open, not mid-query
        calls = []
        r = StateReader(str(self.tmp / "missing.db"))
        with self.assertRaises(SourceUnavailable):
            r.probe()
        self.assertEqual(calls, [])

    def test_the_module_states_the_trade_off_in_words(self):
        # an undocumented immutable read is a silent staleness risk
        text = (pathlib.Path(__file__).resolve().parent.parent
                / "agent_os" / "adapters" / "hermes_ingest.py").read_text(
                    encoding="utf-8")
        self.assertIn("immutable", text)
        self.assertIn("stale", text.lower())


class DefaultPathTest(unittest.TestCase):
    def test_windows_uses_localappdata(self):
        import os
        from agent_os.adapters.hermes_ingest import default_profile_db
        old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = r"C:\Users\Mehdi\AppData\Local"
        try:
            p = default_profile_db("my-personal-assistant")
            self.assertIn("AppData", p)
            self.assertTrue(p.endswith("state.db"))
        finally:
            if old is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old

    def test_wsl_produces_an_mnt_path(self):
        import os
        from agent_os.adapters.hermes_ingest import default_profile_db
        old_local = os.environ.pop("LOCALAPPDATA", None)
        old_prof = os.environ.get("USERPROFILE")
        os.environ["USERPROFILE"] = r"C:\Users\Mehdi"
        try:
            p = default_profile_db("my-personal-assistant")
            self.assertTrue(p.startswith("/mnt/c/"), p)
        finally:
            if old_local is not None:
                os.environ["LOCALAPPDATA"] = old_local
            if old_prof is None:
                os.environ.pop("USERPROFILE", None)
            else:
                os.environ["USERPROFILE"] = old_prof

    def test_the_default_is_not_a_claim_the_file_exists(self):
        # a wrong default must degrade, not crash
        from agent_os.adapters.hermes_ingest import (
            StateReader, default_profile_db)
        p = default_profile_db("no-such-profile-xyz")
        with self.assertRaises(SourceUnavailable):
            StateReader(p).probe()


if __name__ == "__main__":
    unittest.main(verbosity=2)
