# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Fake executor adapter for enforcement testing.

Simulates executor behaviors without any real execution:
- "success":           completes with diff + test report
- "missing_evidence":  claims completion but no test report
- "crash_after_effect": dies after (simulated) side effect -> unknown outcome

The tool inventory is FIXED. A proposal asking for an action outside
allowed_actions is refused at dispatch time; the inventory cannot be
enlarged by any proposal or approval.
"""

from __future__ import annotations

from ..models import Job, WorkerLostError, WorkerOutcome


class FakeExecutor:
    name = "fake-executor"
    allowed_actions = frozenset({"read_file", "write_file", "run_tests", "delete_file"})

    def __init__(self, behavior: str = "success"):
        if behavior not in {"success", "missing_evidence", "crash_after_effect", "delete_file"}:
            raise ValueError(f"unknown behavior: {behavior}")
        self.behavior = behavior
        self.invocations: list[dict] = []

    def run(self, job: Job, attempt: int) -> WorkerOutcome:
        self.invocations.append({"job_id": job.id, "attempt": attempt})
        if self.behavior == "crash_after_effect":
            raise WorkerLostError("simulated crash after side effect")
        if self.behavior == "missing_evidence":
            return WorkerOutcome(status="completed_missing_evidence", evidence={"diff": "+ partial"})
        if self.behavior == "delete_file":
            # Simulate a file deletion with evidence
            return WorkerOutcome(
                status="completed_with_evidence",
                evidence={"diff": "- deleted file", "test_report": "file removed"},
            )
        return WorkerOutcome(
            status="completed_with_evidence",
            evidence={"diff": "+ fixed", "test_report": "3 passed, 0 failed"},
        )
