"""Pure approval/scope validation. Deny must happen before dispatch.

This module contains no I/O: it never touches the executor, the database
or the network. It only decides whether a dispatch would be authorized.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Approval, ApprovalDecision, Job


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
    return None
