# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Concurrent dispatch spends one approval exactly once.

H1 (review of 2026-10-05): ControlService.dispatch() calls
store.consume_approval() and used to DISCARD its return value, then run the
executor unconditionally. The store's RLock serializes each individual
store CALL - not the check-then-act sequence between them - so two threads
that both passed validate_dispatch while the approval was still unspent
would BOTH execute the worker on that single approval: single-use held in
the SQL row but not at the execution level, and the shared dedup key
(`dispatch:{job_id}:{attempt}`) would record only ONE "dispatched" event,
making the double execution invisible in the audit trail.

tests/test_phase5.py's docstring used to claim a concurrency test "would
need a second process to be meaningful". That is true of the store's
internals but false of dispatch()'s sequence, which is what this test pins.

The race window is forced deterministically rather than left to the
scheduler: agent_os.syscall.validate_dispatch is wrapped so both threads
complete the policy check (and therefore read the job's pre-dispatch
state) before either can spend the approval.

  - unfixed code: both threads continue past the barrier, one
    consume_approval() returns rowcount=0 and is ignored, both run the
    adapter -> invocations == 2 -> RED.
  - fixed code: the atomic consume decides a single winner BEFORE any job
    state is written; the loser is refused "approval_already_consumed"
    without touching state or the trail -> invocations == 1 -> GREEN.
"""

from __future__ import annotations

import shutil
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os import service as service_mod
from agent_os import syscall as sc
from agent_os.adapters.fake import FakeExecutor
from agent_os.models import (
    ApprovalDecision,
    DispatchRefused,
    JobState,
    Principal,
)
from agent_os.service import ControlService

T0 = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
T2 = T0 + timedelta(hours=2)

HUMAN = Principal.HUMAN
PLANNER = Principal.PLANNER

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class DispatchSingleWinnerUnderConcurrencyTest(unittest.TestCase):
    """Exactly one of two simultaneous dispatches may run the worker."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db_path = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db_path.exists():
            self.db_path.unlink()
        self.svc = ControlService(self.db_path)
        self._original_validate = sc.validate_dispatch

    def tearDown(self):
        sc.validate_dispatch = self._original_validate
        self.svc.close()
        shutil.rmtree(TMP, ignore_errors=True)

    def _approved_job(self):
        """mission -> planner proposal -> approval request -> human grant."""
        mission = self.svc.create_mission("concurrent dispatch", now=T0)
        self.svc.activate_mission(mission.id)
        job = self.svc.record_proposal(
            mission_id=mission.id,
            title="two threads, one approval",
            executor="fake-executor",
            workspace_paths=("workspaces/mission-1/",),
            actions=("run_tests",),
            proposed_by=PLANNER,
            now=T0,
        )
        approval = self.svc.request_approval(job.id, expires_at=T2, now=T0)
        self.svc.decide(approval.id, ApprovalDecision.GRANTED, HUMAN, now=T0)
        return mission, job, approval

    def test_two_simultaneous_dispatches_run_the_worker_exactly_once(self):
        mission, job, approval = self._approved_job()
        adapter = FakeExecutor(behavior="success")

        barrier = threading.Barrier(2, timeout=10)
        original = self._original_validate

        def synchronized_validate(j, a, now):
            denial = original(j, a, now)
            # Both threads are held here AFTER their policy check (and
            # their A6 state read) but BEFORE either can spend the
            # approval - the exact window H1 lived in.
            barrier.wait()
            time.sleep(0.15)
            return denial

        sc.validate_dispatch = synchronized_validate

        receipts: list = []
        refusals: list = []
        errors: list = []
        out_lock = threading.Lock()

        # Explicit clock: the fixture's T0/T2 are fixed datetimes, while an
        # unqualified dispatch() uses real utc_now() (which would see the
        # grant as expired and refuse both threads for the wrong reason).
        clock = T0 + timedelta(minutes=30)

        def dispatch_once():
            try:
                receipt = self.svc.dispatch(job.id, adapter, now=clock)
                with out_lock:
                    receipts.append(receipt)
            except DispatchRefused as e:
                with out_lock:
                    refusals.append(e)
            except Exception as e:  # pragma: no cover - failure reporting
                with out_lock:
                    errors.append(e)

        threads = [threading.Thread(target=dispatch_once) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            self.assertFalse(t.is_alive(), "dispatch thread hung")

        self.assertEqual(errors, [], f"unexpected errors: {errors}")

        # THE invariant: one approval, one execution.
        self.assertEqual(
            len(adapter.invocations),
            1,
            f"one approval executed the worker {len(adapter.invocations)} times",
        )

        # Exactly one real (non-duplicated) execution was reported; the
        # losing thread is refused before it can touch any state (a
        # duplicated receipt instead would mean it saw the winner's finish
        # - also acceptable, but never a second real run).
        real = [r for r in receipts if not r.duplicated]
        self.assertEqual(
            len(real), 1, f"receipts={receipts} refusals={refusals}"
        )
        self.assertEqual(len(receipts) + len(refusals), 2)

        # The approval is spent exactly once and the job settled normally
        # - not stuck in DISPATCHED/RUNNING by the losing thread.
        stored = self.svc.store.get_approval(approval.id)
        self.assertIsNotNone(stored.consumed_at, "approval must be spent")
        final = self.svc.store.get_job(job.id)
        self.assertIn(
            final.state,
            (JobState.COMPLETED_VERIFIED, JobState.COMPLETED_UNVERIFIED),
            f"job left in {final.state}",
        )


    def test_api_reaches_the_store_through_locked_helpers_only(self):
        """A1 (review 2026-10-05): api.py ran its list SELECTs directly on
        store.conn, outside store._lock, while ThreadingHTTPServer serves
        GETs concurrently - so the documented "every store access is
        serialized by one RLock" invariant was false. SQL lives behind the
        lock in store.py; the API may only call locked helpers.
        """
        import pathlib

        import agent_os.api as api_mod

        src = pathlib.Path(api_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn(
            "conn.execute",
            src,
            "api.py executes SQL outside Store._lock again (A1 regression)",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
