# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Pure approval/scope validation. Deny must happen before dispatch.

This module contains no I/O: it never touches the executor, the database
or the network. It only decides whether a dispatch would be authorized.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Approval, ApprovalAction, ApprovalDecision, Job


def validate_dispatch(job: Job, approval: Optional[Approval], now: datetime) -> Optional[str]:
    """Return a denial reason string, or None when dispatch is allowed.

    Checks (all must pass; first failure wins):
      1. an approval record exists
      2. it is GRANTED (not merely requested)
      3. it has not expired
      4. the destination/executor matches the approved scope exactly
      5. the job manifest hash still matches what was approved
      6. every requested workspace path is inside the approved scope
      7. every requested action is inside the approved scope
      8. the command the job would run is byte-identical to the one the
         approval was granted over
      9. the approval has not been consumed (single-use)
     10. the approval's bound action is among the job's requested actions

    Check 8 is the one that makes the approval about a real operation. Until
    it existed, a grant said "run_tests in /w on subprocess-executor" while
    the effect was whatever argv job.command held - the human decided blind.
    The manifest hash (check 5) already changed when the command changed, so
    this is not closing an exploitable hole; it is replacing an implicit
    dependency on one hash function with an explicit structural comparison.

    Equality is on the stored canonical string, so this compares exactly what
    the approval was granted over, with no re-encoding that could normalize two
    different commands into one.
    """
    if approval is None:
        return "no_approval_record"
    if approval.decision is not ApprovalDecision.GRANTED:
        return f"approval_not_granted:{approval.decision.value}"
    if approval.expires_at is not None and now >= approval.expires_at:
        return "approval_expired"
    if approval.scope.executor != job.executor:
        return f"destination_not_approved:{job.executor}"
    if approval.manifest_hash != job.manifest_hash:
        return "manifest_changed_new_decision_required"
    for path in job.workspace_paths:
        if path not in approval.scope.workspace_paths:
            return f"path_not_in_scope:{path}"
    for action in job.actions:
        if action not in approval.scope.actions:
            return f"action_not_in_scope:{action}"
    if approval.scope.command != job.command:
        # Do not echo either command in the reason: it is caller-supplied and
        # this string reaches the UI and the event log.
        return "command_not_in_scope"
    # Check 9: single-use. A consumed approval is dead.
    if approval.consumed_at is not None:
        return "approval_already_consumed"
    # Check 10: action binding. The approval authorizes ONE specific action.
    if approval.scope.action is not None:
        if not job.actions or approval.scope.action not in job.actions:
            return f"action_not_approved:{approval.scope.action}"
    return None
