# -*- coding: utf-8 -*-
"""F1: an approval must be about a real operation, not a label.

The defect, measured before the fix: the approval object the human reads
contained no reference to the command at all.

    scope = {'executor': 'subprocess-executor',
             'workspace_paths': ['/w'],
             'actions': ['run_tests']}
    job.command = '["python","-c","import shutil; shutil.rmtree(...)"]'

So a human granted "run tests in /w" and the effect of that grant was whatever
argv the job happened to carry. The grant was a decision made blind.

To be precise about severity, because it was overstated when first found: this
was NOT an exploitable bypass. `manifest_hash` is captured from the job at
approval time and re-checked at dispatch, so changing the command already
invalidated the grant (proven by
test_control_service.py::test_a2_manifest_change_after_grant_requires_new_decision).
What was missing is STRUCTURE: the command is now part of the approved scope
itself, checked explicitly, instead of being implied by one hash function.

What these tests pin:
  - the command is visible in what the human is shown
  - a job with a command cannot be authorized by a scope that omits it
  - a caller cannot smuggle a command in through the request body (decision 4)
  - approval rows written before the fix still load, and do NOT act as wildcard
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from agent_os.api import AgentOSApi, _approval_to_dict
from agent_os.models import (
    ApprovalDecision,
    ApprovalScope,
    Job,
    JobState,
    Principal,
    encode_command,
    utc_now,
)
from agent_os.policy import validate_dispatch
from agent_os.service import ControlService
from agent_os.store import Store

PLANNER = Principal.PLANNER
HUMAN = Principal.HUMAN


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="f1-"))
        self.svc = ControlService(self.tmp / "s.db")
        self.addCleanup(self.svc.close)
        self.mission = self.svc.create_mission("F1")
        self.src = self.tmp / "src"
        self.src.mkdir()
        (self.src / "marker.txt").write_text("original", encoding="utf-8")

    def _job(self, command=None, actions=("run_tests",)):
        return self.svc.record_proposal(
            self.mission.id, "t", "subprocess-executor", (str(self.src),),
            actions, PLANNER, command=command,
        )


class ScopeCarriesTheCommandTest(_Base):
    def test_the_default_scope_is_copied_from_the_job(self):
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        self.assertEqual(appr.scope.command, job.command)

    def test_what_the_human_is_shown_names_the_command(self):
        # The whole point. Measured before the fix: the key was absent.
        job = self._job(["python", "-c", "print('hello')"])
        appr = self.svc.request_approval(job.id)
        public = _approval_to_dict(appr)
        self.assertIn("command", public["scope"])
        self.assertEqual(public["scope"]["command"], ["python", "-c", "print('hello')"])

    def test_the_shell_command_is_rendered_as_argv_not_the_storage_string(self):
        # A decision surface showing '["python","-c",...]' is still awkward to
        # read; showing the argv is what a human can actually judge.
        job = self._job(["python", "-m", "pytest"])
        public = _approval_to_dict(self.svc.request_approval(job.id))
        self.assertIsInstance(public["scope"]["command"], list)

    def test_a_job_with_no_command_yields_a_none_command(self):
        job = self._job(None)
        self.assertIsNone(self.svc.request_approval(job.id).scope.command)

    def test_the_command_survives_the_store_round_trip(self):
        job = self._job(["python", "-c", "print('round trip')"])
        appr = self.svc.request_approval(job.id)
        self.svc.decide(appr.id, ApprovalDecision.GRANTED, HUMAN)
        stored = self.svc.store.get_approval(appr.id)
        self.assertEqual(stored.scope.command, '["python","-c","print(\'round trip\')"]')

    def test_the_command_is_really_persisted_not_derived_on_read(self):
        # If it were re-derived from the job on every read, the scope would be
        # decorative and the dispatch check would prove nothing.
        job = self._job(["python", "-c", "print(1)"])
        appr = self.svc.request_approval(job.id)
        raw = self.svc.store.conn.execute(
            "SELECT scope_json FROM approvals WHERE id=?", (appr.id,)
        ).fetchone()[0]
        self.assertIn("command", json.loads(raw))


class ScopeWithoutTheCommandCannotAuthorizeOneTest(_Base):
    """A scope with no command must not authorize a job that has one.

    These build the scope the only way it can still exist: by writing a
    pre-fix approval ROW directly into the database. Passing a hand-built
    ApprovalScope to request_approval no longer works, because the service
    overwrites the command from the job - that is the point of the fix. So the
    refusal path is now reachable only through rows written before the fix,
    which is exactly where it matters: an existing database.

    A scope object is still used below where the point is the policy function
    in isolation, with the object built by hand and never passed through the
    service.
    """

    def _legacy_row(self, scope_json: dict) -> str:
        """Write an approval row exactly as the pre-fix code wrote it, and
        return its id. The job keeps its real command."""
        import uuid
        aid = f"appr-{uuid.uuid4().hex[:12]}"
        self.svc.store.conn.execute(
            "INSERT INTO approvals (id, job_id, decision, scope_json, requested_at,"
            " decided_at, decided_by, expires_at, manifest_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (aid, self._job_id, "granted", json.dumps(scope_json),
             utc_now().isoformat(), utc_now().isoformat(), "human", None,
             self._job_hash),
        )
        self.svc.store.conn.commit()
        return aid

    def setUp(self):
        super().setUp()
        job = self._job(["python", "-c", "print('x')"])
        self._job_id = job.id
        self._job_hash = job.manifest_hash

    def test_a_scope_omitting_the_command_refuses_a_job_that_has_one(self):
        # The F1 property, through a real pre-fix row in a real database.
        aid = self._legacy_row({
            "executor": "subprocess-executor",
            "workspace_paths": [str(self.src)],
            "actions": ["run_tests"],
        })
        job = self.svc.store.get_job(self._job_id)
        denial = validate_dispatch(job, self.svc.store.get_approval(aid), utc_now())
        self.assertEqual(denial, "command_not_in_scope")

    def test_a_scope_carrying_a_different_command_is_refused(self):
        aid = self._legacy_row({
            "executor": "subprocess-executor",
            "workspace_paths": [str(self.src)],
            "actions": ["run_tests"],
            "command": encode_command(["echo", "innocuous"]),
        })
        job = self.svc.store.get_job(self._job_id)
        denial = validate_dispatch(job, self.svc.store.get_approval(aid), utc_now())
        self.assertEqual(denial, "command_not_in_scope")

    def test_a_scope_with_the_matching_command_is_allowed(self):
        job = self.svc.store.get_job(self._job_id)
        aid = self._legacy_row({
            "executor": "subprocess-executor",
            "workspace_paths": [str(self.src)],
            "actions": ["run_tests"],
            "command": job.command,
        })
        self.assertIsNone(
            validate_dispatch(job, self.svc.store.get_approval(aid), utc_now())
        )

    def test_both_jobs_without_a_command_are_still_allowed(self):
        job = self._job(None)
        appr = self.svc.request_approval(job.id)
        self.svc.decide(appr.id, ApprovalDecision.GRANTED, HUMAN)
        self.assertIsNone(
            validate_dispatch(job, self.svc.store.get_approval(appr.id), utc_now())
        )

    def test_the_denial_reason_does_not_echo_the_command(self):
        # The reason reaches the UI and the event log; the argv can be long and
        # is caller-supplied.
        aid = self._legacy_row({
            "executor": "subprocess-executor",
            "workspace_paths": [str(self.src)],
            "actions": ["run_tests"],
        })
        job = self.svc.store.get_job(self._job_id)
        denial = validate_dispatch(job, self.svc.store.get_approval(aid), utc_now())
        self.assertNotIn("print", denial)

    def test_dispatch_is_refused_end_to_end_not_just_by_the_pure_function(self):
        from agent_os.adapters.subprocess_executor import SubprocessExecutor
        from agent_os.service import DispatchRefused
        aid = self._legacy_row({
            "executor": "subprocess-executor",
            "workspace_paths": [str(self.src)],
            "actions": ["run_tests"],
        })
        job = self.svc.store.get_job(self._job_id)
        # The job must look approvable in state, or the refusal we measure is
        # the state machine and not the command check.
        self.svc.store.update_job(self._job_id, state=JobState.APPROVED)
        job = self.svc.store.get_job(self._job_id)
        runner = SubprocessExecutor(source_workspace=self.src, timeout_seconds=10)
        with self.assertRaises(DispatchRefused) as ctx:
            self.svc.dispatch(self._job_id, runner)
        self.assertEqual(ctx.exception.reason, "command_not_in_scope")
        self.assertEqual(runner.invocations, [],
                         "the executor must not even be reached")


class CallerCannotSetTheCommandTest(_Base):
    """Decision 4: a caller-supplied scope may propose BOUNDS, never the
    payload. Otherwise the scope and the job disagree and the human grants one
    thing while another runs - F1 reachable from the request body."""

    def _api(self):
        # A real AgentOSApi, not a __new__ shell: _request_approval reaches
        # self.service, and a half-built object would fail for a reason that has
        # nothing to do with the behaviour under test.
        return AgentOSApi(self.svc, token=None)

    def test_a_body_command_is_ignored(self):
        # The body's command is discarded and the job's own command is used
        # instead. NOT None: an approval with no command would be exactly the
        # blind grant F1 is about, even though dispatch would then refuse.
        job = self._job(["python", "-c", "print('real')"])
        api = self._api()
        appr = api._request_approval({
            "job_id": job.id,
            "scope": {
                "executor": "subprocess-executor",
                "workspace_paths": [str(self.src)],
                "actions": ["run_tests"],
                "command": ["echo", "attacker-chosen"],
            },
        })
        self.assertEqual(appr.scope.command, job.command)
        self.assertNotIn("attacker-chosen", appr.scope.command)

    def test_a_body_command_cannot_strip_the_real_one(self):
        # Found by the proof script: passing `command: None` in the body used
        # to leave the scope with no command at all. Fail-closed, but it showed
        # the human a scope that did not describe the operation.
        job = self._job(["python", "-c", "print('real')"])
        api = self._api()
        appr = api._request_approval({
            "job_id": job.id,
            "scope": {
                "executor": "subprocess-executor",
                "workspace_paths": [str(self.src)],
                "actions": ["run_tests"],
                "command": None,
            },
        })
        self.assertEqual(appr.scope.command, job.command)

    def test_the_service_itself_cannot_be_made_to_drop_the_command(self):
        # Defence in depth for the same rule at the layer below the API.
        job = self._job(["python", "-c", "print('real')"])
        stripped = ApprovalScope(
            executor="subprocess-executor", workspace_paths=(str(self.src),),
            actions=("run_tests",), command=None,
        )
        appr = self.svc.request_approval(job.id, scope=stripped)
        self.assertEqual(appr.scope.command, job.command)

    def test_a_scope_with_a_foreign_command_is_overwritten_not_trusted(self):
        job = self._job(["python", "-c", "print('real')"])
        wrong = ApprovalScope(
            executor="subprocess-executor", workspace_paths=(str(self.src),),
            actions=("run_tests",), command=encode_command(["echo", "other"]),
        )
        appr = self.svc.request_approval(job.id, scope=wrong)
        self.assertEqual(appr.scope.command, job.command)

    def test_the_service_overwrites_even_when_the_api_is_bypassed(self):
        # Added because mutation F1-M7 survived: gating the overwrite on
        # `if scope.command is None` leaves the behaviour intact through the
        # API, because the API already forces None. Only a direct service
        # caller can tell the difference, so this test calls the service.
        job = self._job(["python", "-c", "print('real')"])
        for supplied in (None, encode_command(["echo", "substituted"])):
            with self.subTest(supplied=supplied):
                hostile = ApprovalScope(
                    executor="subprocess-executor",
                    workspace_paths=(str(self.src),),
                    actions=("run_tests",),
                    command=supplied,
                )
                appr = self.svc.request_approval(job.id, scope=hostile)
                self.assertEqual(appr.scope.command, job.command)
                self.svc.store.conn.execute(
                    "DELETE FROM approvals WHERE id=?", (appr.id,)
                )
                self.svc.store.conn.commit()

    def test_the_ignored_attempt_is_recorded(self):
        # Silence would let a client believe it worked.
        job = self._job(["python", "-c", "print('real')"])
        api = self._api()
        api._request_approval({
            "job_id": job.id,
            "scope": {
                "executor": "subprocess-executor",
                "workspace_paths": [str(self.src)],
                "actions": ["run_tests"],
                "command": ["echo", "attacker-chosen"],
            },
        })
        kinds = [e["kind"] for e in self.svc.store.list_events()]
        self.assertIn("approval.scope_command_ignored", kinds)

    def test_the_ignored_command_cannot_authorize_anything(self):
        # The body value is discarded and replaced with the job's own command,
        # so this grant authorizes exactly the job's real operation - and
        # nothing the caller tried to substitute.
        job = self._job(["python", "-c", "print('real')"])
        api = self._api()
        appr = api._request_approval({
            "job_id": job.id,
            "scope": {
                "executor": "subprocess-executor",
                "workspace_paths": [str(self.src)],
                "actions": ["run_tests"],
                "command": ["echo", "substituted"],
            },
        })
        self.svc.decide(appr.id, ApprovalDecision.GRANTED, HUMAN)
        self.assertIsNone(
            validate_dispatch(job, self.svc.store.get_approval(appr.id), utc_now())
        )
        self.assertEqual(self.svc.store.get_approval(appr.id).scope.command, job.command)

    def test_a_caller_may_still_propose_the_bounds(self):
        # Decision 4 must not overreach: bounds are the point of a request
        # scope, and the human refuses them if they are too wide.
        job = self._job(["python", "-c", "print('real')"])
        api = self._api()
        appr = api._request_approval({
            "job_id": job.id,
            "scope": {
                "executor": "subprocess-executor",
                "workspace_paths": [str(self.src)],
                "actions": ["run_tests"],
            },
        })
        self.assertEqual(appr.scope.executor, "subprocess-executor")
        self.assertEqual(appr.scope.actions, ("run_tests",))


class PreFixApprovalRowsTest(unittest.TestCase):
    """Migration, chosen deliberately over invalidating old grants: an
    approval row written before `command` joined the scope has no such key.
    Reading it as None is honest - that grant authorized no command - and it
    must NOT become a wildcard."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="f1-legacy-"))
        self.store = Store(self.tmp / "legacy.db")
        self.addCleanup(self.store.close)
        self.mission = self.store.create_mission("legacy")

    def _legacy_scope_row(self, approval_id, command_value=None):
        """Write an approval row by hand, shaped exactly as the pre-fix code
        wrote it: a scope_json with no `command` key."""
        import uuid
        scope = {
            "executor": "subprocess-executor",
            "workspace_paths": ["/w"],
            "actions": ["run_tests"],
        }
        if command_value is not None:
            scope["command"] = command_value
        self.store.conn.execute(
            "INSERT INTO approvals (id, job_id, decision, scope_json, requested_at,"
            " decided_at, decided_by, expires_at, manifest_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (approval_id, "job-x", "granted", json.dumps(scope),
             utc_now().isoformat(), utc_now().isoformat(), "human", None, "hash-x"),
        )
        self.store.conn.commit()

    def _job(self, command):
        return Job(
            id="job-x", mission_id=self.mission.id, title="t",
            proposed_by=Principal.PLANNER, executor="subprocess-executor",
            workspace_paths=("/w",), actions=("run_tests",),
            state=JobState.APPROVED, attempt_no=0, manifest_hash="hash-x",
            created_at="t", updated_at="t", command=command,
        )

    def test_a_pre_fix_row_still_loads(self):
        self._legacy_scope_row("appr-old")
        loaded = self.store.get_approval("appr-old")
        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.scope.command)

    def test_a_pre_fix_row_does_not_authorize_a_command(self):
        # The point of reading it as None rather than as a wildcard.
        self._legacy_scope_row("appr-old")
        loaded = self.store.get_approval("appr-old")
        job = self._job(encode_command(["python", "-c", "print(1)"]))
        self.assertEqual(
            validate_dispatch(job, loaded, utc_now()), "command_not_in_scope"
        )

    def test_a_pre_fix_row_still_authorizes_a_commandless_job(self):
        # Nothing regressed for the case it was actually written for.
        self._legacy_scope_row("appr-old")
        loaded = self.store.get_approval("appr-old")
        self.assertIsNone(validate_dispatch(self._job(None), loaded, utc_now()))

    def test_listing_a_pre_fix_approval_does_not_raise(self):
        self._legacy_scope_row("appr-old")
        public = _approval_to_dict(self.store.get_approval("appr-old"))
        self.assertIsNone(public["scope"]["command"])

    def test_the_scope_stayed_in_the_existing_json_blob(self):
        # The column is already a JSON blob, which is why the F1 fix was one
        # commit with no migration. If a future change adds a real column, this
        # test is the reminder that the old path was taken on purpose.
        #
        # Renamed from test_no_schema_migration_was_needed when Phase 3 bumped
        # SCHEMA_VERSION for an unrelated reason (the tools table). The claim
        # itself is about the approvals TABLE, not the global version, so the
        # assertion moved to the constant and the name now says what is
        # actually being defended.
        cols = {
            r[1]: r[2]
            for r in self.store.conn.execute("PRAGMA table_info(approvals)").fetchall()
        }
        self.assertEqual(cols["scope_json"].upper(), "TEXT")
        ver = self.store.conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        from agent_os.store import SCHEMA_VERSION
        self.assertEqual(
            int(ver), SCHEMA_VERSION,
            "F1 must not change SCHEMA_VERSION; only a schema change may. "
            "The version is now expected to move only for a real schema "
            "change - Phase 3 (the tools table) was the last one.",
        )


class ManifestHashIsStillALiveGuardTest(_Base):
    """The F1 check is a SECOND line, not a replacement. These keep the first
    one honest: if the new check could pass while the command changed, that
    would mean the structural comparison is doing nothing."""

    def test_amending_the_command_still_changes_the_manifest_hash(self):
        job = self._job(["python", "-c", "print('before')"])
        before = job.manifest_hash
        after = self.svc.amend_job(job.id, command=["python", "-c", "print('after')"])
        self.assertNotEqual(before, after.manifest_hash)

    def test_amending_the_command_invalidates_the_grant(self):
        job = self._job(["python", "-c", "print('before')"])
        appr = self.svc.request_approval(job.id)
        self.svc.decide(appr.id, ApprovalDecision.GRANTED, HUMAN)
        self.svc.amend_job(job.id, command=["python", "-c", "print('after')"])
        amended = self.svc.store.get_job(job.id)
        denial = validate_dispatch(amended, self.svc.store.get_approval(appr.id), utc_now())
        self.assertTrue(
            denial.startswith(("manifest_changed", "command_not_in_scope")),
            f"amended job dispatched on a stale grant: {denial}",
        )

    def test_two_jobs_with_different_commands_get_different_manifest_hashes(self):
        a = self._job(["python", "-c", "print('a')"])
        b = self._job(["python", "-c", "print('b')"])
        self.assertNotEqual(a.manifest_hash, b.manifest_hash)

    def test_the_manifest_check_runs_before_the_command_check(self):
        # Added because mutation F1-M13 survived. The test above accepts EITHER
        # reason, which is the right thing for that test's purpose but means it
        # cannot see ordering. Order matters for the operator: "your approval
        # is stale, ask again" is actionable, while "command not in scope" on a
        # job the human did approve reads as a false accusation.
        job = self._job(["python", "-c", "print('before')"])
        appr = self.svc.request_approval(job.id)
        self.svc.decide(appr.id, ApprovalDecision.GRANTED, HUMAN)
        self.svc.amend_job(job.id, command=["python", "-c", "print('after')"])
        amended = self.svc.store.get_job(job.id)
        self.assertEqual(
            validate_dispatch(amended, self.svc.store.get_approval(appr.id), utc_now()),
            "manifest_changed_new_decision_required",
        )


if __name__ == "__main__":
    unittest.main()
