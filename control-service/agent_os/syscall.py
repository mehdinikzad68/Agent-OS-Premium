# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""The single gate every action must pass through.

Design contract (Phase 1 of the kernel roadmap, see docs/KERNEL-GAP.md):

  * DENY BY DEFAULT. An action this module does not explicitly know how to
    authorize is refused, never allowed. Adding a new action requires adding
    an explicit branch here; there is no fall-through to "allow".
  * FAIL CLOSED. If policy evaluation raises for any reason, the verdict is
    DENY, not ALLOW. This is the deliberate difference from the Hermes gate,
    which is configured fail-open (a crash there means a silent allow).
  * SINGLE PATH. Nothing may reach an executor without a verdict from here.
    dispatch() calls syscall() before it touches the executor; there is no
    second door.

This module is intentionally small and I/O-free with respect to the executor:
it reads state (job, approval) and returns a verdict. It never runs work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .logging_setup import get_logger, log_event
from .models import Approval, DispatchReceipt, Job, utc_now
from .policy import validate_dispatch

_log = get_logger("syscall")

#: The actions this gate knows how to authorize. Anything else is denied.
#: Phase 1 ships exactly one action: "dispatch" (run an approved job).
KNOWN_ACTIONS = frozenset({"dispatch"})

REASON_UNKNOWN_ACTION = "unknown_action"
REASON_NO_JOB = "job_not_found"
REASON_POLICY_ERROR = "policy_error_fail_closed"


@dataclass(frozen=True)
class SyscallRequest:
    """A single request for the kernel to authorize and (if allowed) run.

    agent_id is the principal on whose behalf the request is made. In
    Phase 1 it is recorded for the audit trail; authority is still enforced
    by the approval record, not by the agent's self-declaration.
    """

    agent_id: str
    action: str
    job_id: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SyscallVerdict:
    """The kernel's answer. allowed=False is a refusal, never a soft hint."""

    allowed: bool
    reason: str
    action: str
    agent_id: str
    job_id: str
    receipt: Optional[DispatchReceipt] = None


def _deny(request: SyscallRequest, reason: str) -> SyscallVerdict:
    return SyscallVerdict(
        allowed=False,
        reason=reason,
        action=request.action,
        agent_id=request.agent_id,
        job_id=request.job_id,
    )


def evaluate(
    request: SyscallRequest,
    job: Optional[Job],
    approval: Optional[Approval],
    now: datetime,
) -> SyscallVerdict:
    """Decide a request WITHOUT running anything. Pure, so it is testable.

    Order (first failure wins):
      1. unknown action            -> DENY  (deny by default)
      2. missing job               -> DENY
      3. policy evaluation         -> DENY on any denial reason
      4. policy raises             -> DENY  (fail closed)
    A clean pass returns an allowed verdict with no receipt yet; the caller
    performs the work and attaches the receipt.
    """
    if request.action not in KNOWN_ACTIONS:
        return _deny(request, REASON_UNKNOWN_ACTION)

    if job is None:
        return _deny(request, REASON_NO_JOB)

    try:
        denial = validate_dispatch(job, approval, now)
    except Exception:  # noqa: BLE001 - fail-closed is the whole point
        log_event(
            _log,
            40,
            "syscall.policy_error",
            action=request.action,
            agent_id=request.agent_id,
            job_id=request.job_id,
            exc_info=True,
        )
        return _deny(request, REASON_POLICY_ERROR)

    if denial is not None:
        return _deny(request, denial)

    return SyscallVerdict(
        allowed=True,
        reason="allowed",
        action=request.action,
        agent_id=request.agent_id,
        job_id=request.job_id,
    )


def syscall(service, request: SyscallRequest, now: Optional[datetime] = None) -> SyscallVerdict:
    """The single gate. Reads state, evaluates, records the verdict, returns it.

    service is a ControlService; it is used for read-only state access
    (get_job, latest_approval_for_job) and for recording the verdict event.
    This function does NOT execute the action: dispatch() does, and only
    after this returns an allowed verdict.
    """
    now = now or utc_now()
    job = service.store.get_job(request.job_id)
    approval = service.store.latest_approval_for_job(request.job_id)

    verdict = evaluate(request, job, approval, now)

    # Every verdict is auditable, allowed or not. A refusal is the more
    # interesting record, so it is never silent.
    service.store.record_event(
        "syscall_verdict",
        {
            "action": request.action,
            "agent_id": request.agent_id,
            "job_id": request.job_id,
            "allowed": verdict.allowed,
            "reason": verdict.reason,
        },
    )
    if not verdict.allowed:
        log_event(
            _log,
            30,
            "syscall.denied",
            action=request.action,
            agent_id=request.agent_id,
            job_id=request.job_id,
            reason=verdict.reason,
        )
    return verdict
