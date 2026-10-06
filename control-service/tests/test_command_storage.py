# -*- coding: utf-8 -*-
"""The F8 fix: `command` is stored as canonical JSON argv, and an unreadable
stored value fails closed instead of crashing.

Defect F8: the jobs.command column is TEXT, and sqlite cannot bind a list, so
every argv list that passed the new edge validation died one layer down with

    ProgrammingError: Error binding parameter 13: type 'list' is not supported

which meant --enable-subprocess could not accept a single real command. A JSON
string would not help either: Popen treats a string as a single program name and
raises FileNotFoundError. So the field is serialized on the way in and parsed on
the way out, in exactly one place each (models.encode_command /
models.decode_command).

The migration half matters more than the happy path. Rows written before this fix
can hold anything, so the executor must refuse them with a message an operator
can act on rather than a traceback from three frames down. That refusal is the
test that would have caught the original defect's real-world consequence, and it
is the one most likely to be deleted later as "impossible" - hence it is pinned
here.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_os.adapters.subprocess_executor import SubprocessExecutor
from agent_os.models import (
    CommandFormatError,
    Job,
    JobState,
    Principal,
    decode_command,
    encode_command,
    utc_now,
)
from agent_os.service import ControlService
from agent_os.store import Store


# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

class EncodeDecodeTest(unittest.TestCase):
    def test_round_trip_preserves_argv_exactly(self):
        argv = ["python", "-c", "print('hi')", "--flag=a b", "quote'\"inside"]
        self.assertEqual(decode_command(encode_command(argv)), argv)

    def test_none_stays_none_rather_than_becoming_the_text_null(self):
        # Both sides of the boundary treat absent as "no command", and the
        # executor reports that with its own message. Encoding it as the string
        # "null" would move a clear message to a decode error.
        self.assertIsNone(encode_command(None))
        self.assertIsNone(decode_command(None))

    def test_the_encoding_is_canonical_and_has_no_spaces(self):
        # Phase 5 binds an approval to the exact argv, so the encoding has to
        # be byte-stable. A default json.dumps with spaces is still stable but
        # the compact form is the contract; assert it rather than assume it.
        self.assertEqual(encode_command(["a", "b"]), '["a","b"]')

    def test_the_same_argv_always_encodes_identically(self):
        a = encode_command(["x", "1", "--k=v"])
        b = encode_command(["x", "1", "--k=v"])
        self.assertEqual(a, b)

    def test_non_ascii_arguments_survive_the_round_trip(self):
        # ensure_ascii=False keeps them readable in the DB. If someone reverts
        # that flag the value still round-trips, so pin readability instead.
        encoded = encode_command(["echo", "سلام"])
        self.assertIn("سلام", encoded)

    def test_encode_refuses_a_non_list_rather_than_stringifying_it(self):
        # Silently accepting a string here would rebuild the original bug one
        # layer up: json.dumps("echo hi") is valid JSON that decodes back to a
        # string, and Popen would then raise FileNotFoundError.
        for bad in ("echo hi", 42, {"a": 1}, ("echo", "hi")):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(TypeError):
                    encode_command(bad)

    def test_decode_round_trips_what_encode_produced(self):
        self.assertEqual(decode_command('["a","b"]'), ["a", "b"])


class DecodeFailsClosedTest(unittest.TestCase):
    """Parsing is not validation. Each case below parses successfully as JSON
    yet is not argv, which is why a bare json.loads would not be enough."""

    def test_a_json_number_is_refused(self):
        with self.assertRaises(CommandFormatError):
            decode_command("1")

    def test_a_json_object_is_refused(self):
        with self.assertRaises(CommandFormatError):
            decode_command('{"cmd":"echo hi"}')

    def test_a_json_string_is_refused(self):
        # This is the shape that made the original fix tempting-but-wrong: it
        # parses, and Popen reads it as a single program name.
        with self.assertRaises(CommandFormatError):
            decode_command('"echo hi"')

    def test_a_json_null_is_refused(self):
        with self.assertRaises(CommandFormatError):
            decode_command("null")

    def test_an_empty_array_is_refused(self):
        with self.assertRaises(CommandFormatError):
            decode_command("[]")

    def test_an_array_with_a_non_string_is_refused(self):
        with self.assertRaises(CommandFormatError):
            decode_command('["echo",7]')

    def test_an_array_with_an_empty_string_is_refused(self):
        with self.assertRaises(CommandFormatError):
            decode_command('["echo",""]')

    def test_unparseable_text_is_refused_with_an_actionable_message(self):
        # This is the pre-fix row: a raw argv was never stored, but a hand-
        # edited or future-format value can still land here.
        with self.assertRaises(CommandFormatError) as c:
            decode_command("python -c print(1)")
        self.assertIn("re-propose", str(c.exception))

    def test_a_non_string_input_is_refused_before_parsing(self):
        with self.assertRaises(CommandFormatError):
            decode_command(["already", "a", "list"])

    def test_the_error_is_a_value_error_so_existing_handlers_still_work(self):
        # Subclasses ValueError on purpose: the executor catches it, but a
        # generic `except ValueError` elsewhere keeps working.
        self.assertTrue(issubclass(CommandFormatError, ValueError))


class ExecutorRefusesUnreadableCommandTest(unittest.TestCase):
    """The migration contract, proven through the real executor: a job row
    whose command cannot be decoded must NOT reach Popen."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="f8-exec-"))
        self.src = self.tmp / "src"
        self.src.mkdir()
        self.runner = SubprocessExecutor(source_workspace=self.src, timeout_seconds=10)

    def _job(self, stored):
        return Job(
            id="job-f8",
            mission_id="m",
            title="t",
            proposed_by=Principal.PLANNER,
            executor="subprocess-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            state=JobState.APPROVED,
            attempt_no=0,
            manifest_hash="x",
            created_at="t",
            updated_at="t",
            command=stored,
        )

    def test_a_legacy_raw_string_command_fails_closed_without_running(self):
        # The pre-fix shape: a bare command line as stored text. Handing this
        # to Popen raises FileNotFoundError inside the executor, which the
        # service reports as a lost worker - i.e. "unknown outcome". Refusing
        # up front is honest: nothing ran, so the outcome IS known.
        job = self._job("python -c print(1)")
        outcome = self.runner.run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertIn("unreadable stored command", outcome.evidence["error"])
        self.assertEqual(self.runner.invocations, [],
                         "nothing may be recorded as invoked when nothing ran")

    def test_the_failure_message_is_specific_about_what_is_wrong(self):
        outcome = self.runner.run(self._job("not json at all"), 1)
        err = outcome.evidence["error"]
        self.assertIn("not valid JSON", err)
        self.assertIn("re-propose", err)

    def test_a_json_scalar_command_fails_closed(self):
        outcome = self.runner.run(self._job("1"), 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertIn("non-empty JSON array", outcome.evidence["error"])

    def test_a_failed_decode_never_produces_evidence(self):
        # Otherwise the service could treat a refusal as a real run.
        outcome = self.runner.run(self._job('{"cmd":"echo hi"}'), 1)
        self.assertEqual(outcome.evidence.get("test_report"), "")
        self.assertNotIn("exit_code", outcome.evidence)

    def test_a_valid_encoded_command_still_actually_runs(self):
        # The control: the refusal path above must not have broken the happy
        # path. A real interpreter, real subprocess, real evidence.
        job = self._job(encode_command([sys.executable, "-c", "print('3 tests passed')"]))
        outcome = self.runner.run(job, 1)
        self.assertEqual(outcome.status, "completed_with_evidence")
        self.assertEqual(outcome.evidence["exit_code"], 0)
        self.assertTrue(outcome.evidence["test_report"])


class StoreRoundTripTest(unittest.TestCase):
    """The actual defect: sqlite cannot bind a list. Prove a real argv list
    survives insert -> read through the real Store, not a mock."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="f8-store-"))
        self.store = Store(self.tmp / "jobs.db")
        self.addCleanup(self.store.close)
        self.mission = self.store.create_mission(
            title="t"
        )

    def _job(self, command):
        return Job(
            id="job-round",
            mission_id="m1",
            title="t",
            proposed_by=Principal.PLANNER,
            executor="subprocess-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            state=JobState.PROPOSED,
            attempt_no=0,
            manifest_hash="h",
            created_at=utc_now().isoformat(),
            updated_at=utc_now().isoformat(),
            command=encode_command(command),
        )

    def test_an_argv_list_survives_insert_and_read(self):
        argv = ["python", "-m", "pytest", "-k", "test_x"]
        self.store.insert_job(self._job(argv))
        loaded = self.store.get_job("job-round")
        self.assertIsNotNone(loaded)
        self.assertEqual(decode_command(loaded.command), argv)

    def test_the_column_really_is_text(self):
        # Pin the storage contract this fix depends on. If a future migration
        # adds a real argv column, these tests should be revisited, not
        # silently kept.
        cols = {
            r[1]: r[2]
            for r in self.store.conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        self.assertEqual(cols["command"].upper(), "TEXT")


class ServiceEncodesAtTheBoundaryTest(unittest.TestCase):
    """record_proposal is called directly by tests, the CLI, and future
    adapters, not only over HTTP. Every one of them writes the same TEXT
    column, so the encoding has to happen inside the service."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="f8-svc-"))
        self.svc = ControlService(self.tmp / "svc.db")
        self.addCleanup(self.svc.close)
        self.mission = self.svc.create_mission("a mission")

    def test_a_direct_list_call_no_longer_raises_a_programming_error(self):
        job = self.svc.record_proposal(
            self.mission.id, "t", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["python", "-c", "print(1)"],
        )
        loaded = self.svc.store.get_job(job.id)
        self.assertEqual(decode_command(loaded.command), ["python", "-c", "print(1)"])

    def test_the_stored_value_is_a_string_so_sqlite_accepts_it(self):
        job = self.svc.record_proposal(
            self.mission.id, "t2", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["echo", "hi"],
        )
        self.assertIsInstance(job.command, str)

    def test_the_manifest_hash_is_computed_over_the_stored_form(self):
        # Two proposals with the same argv must hash identically, and the hash
        # must not depend on list-vs-string at call time - otherwise a caller
        # switching representation would silently invalidate live approvals.
        a = self.svc.record_proposal(
            self.mission.id, "same", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["echo", "hi"],
        )
        b = self.svc.record_proposal(
            self.mission.id, "same", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["echo", "hi"],
        )
        self.assertEqual(a.manifest_hash, b.manifest_hash)

    def test_amend_re_encodes_rather_than_storing_the_list(self):
        job = self.svc.record_proposal(
            self.mission.id, "t3", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["echo", "before"],
        )
        self.svc.amend_job(job.id, command=["echo", "after"])
        loaded = self.svc.store.get_job(job.id)
        self.assertEqual(decode_command(loaded.command), ["echo", "after"])

    def test_amend_invalidates_the_grant_bound_to_the_old_argv(self):
        # The Phase 5 contract, proven: changing the command changes the hash.
        job = self.svc.record_proposal(
            self.mission.id, "t4", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["echo", "before"],
        )
        before = job.manifest_hash
        amended = self.svc.amend_job(job.id, command=["echo", "after"])
        self.assertNotEqual(before, amended.manifest_hash)

    def test_amend_without_a_command_leaves_the_stored_one_alone(self):
        # amend_job used to always pass job.command back to update_job. Now it
        # passes None when nothing changed, so update_job skips the column.
        # The stored value must survive that.
        job = self.svc.record_proposal(
            self.mission.id, "t5", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["echo", "keep"],
        )
        self.svc.amend_job(job.id, actions=("run_tests", "run_command"))
        loaded = self.svc.store.get_job(job.id)
        self.assertEqual(decode_command(loaded.command), ["echo", "keep"])


class ApiReturnsArgvTest(unittest.TestCase):
    """The API accepts a list, so it should return a list. Returning the JSON
    encoding would make a read-after-write round trip look like corruption."""

    def test_a_proposed_job_reads_back_as_the_argv_that_was_sent(self):
        from agent_os.api import _job_to_dict

        tmp = Path(tempfile.mkdtemp(prefix="f8-api-"))
        svc = ControlService(tmp / "api.db")
        self.addCleanup(svc.close)
        mission = svc.create_mission("a mission")
        job = svc.record_proposal(
            mission.id, "t", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["echo", "round trip"],
        )
        self.assertEqual(_job_to_dict(job)["command"], ["echo", "round trip"])

    def test_an_unreadable_legacy_row_lists_without_raising(self):
        # Listing jobs must not 500 because one row predates the fix. The raw
        # value is returned so an operator can see what is actually stored.
        from agent_os.api import _job_to_dict

        tmp = Path(tempfile.mkdtemp(prefix="f8-legacy-"))
        svc = ControlService(tmp / "legacy.db")
        self.addCleanup(svc.close)
        mission = svc.create_mission("a mission")
        job = svc.record_proposal(
            mission.id, "t", "subprocess-executor", ("w/",), ("run_tests",),
            Principal.PLANNER, command=["echo", "ok"],
        )
        # Simulate a pre-fix row by writing raw text over the column.
        svc.store.conn.execute(
            "UPDATE jobs SET command=? WHERE id=?", ("legacy raw text", job.id)
        )
        svc.store.conn.commit()
        loaded = svc.store.get_job(job.id)
        self.assertEqual(_job_to_dict(loaded)["command"], "legacy raw text")


if __name__ == "__main__":
    unittest.main()
