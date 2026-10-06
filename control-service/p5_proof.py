"""Prove single-use still holds after the A6 order was restored.

The claim
---------
A spent approval can never authorise a second execution, even when the job is
put back into a dispatchable state. A6 makes a replay of a FINISHED job
idempotent (nothing runs), so the only way to reach a fresh dispatch is a job
whose state is not terminal. We force exactly that and check the refusal.

This is the test that would have caught the inverted order if it had existed:
with the premature check the refusal came from service.dispatch; with the
restored order it comes from policy check 9 (validate_dispatch). Either way the
ACTION must not run twice - which is the property that matters.

Run with the check present -> PASS.
Run p5_mutation_check.py (policy check 9 AND the dispatch consume gate
removed) -> the second dispatch would execute,
so the proof can fail. That is what makes it a proof and not a tautology.
"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from agent_os.models import ApprovalDecision, JobState, Principal
from agent_os.service import ControlService, DispatchRefused
from agent_os.adapters.fake import FakeExecutor


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="p5-proof-"))
    svc = ControlService(str(tmp / "proof.db"))
    try:
        mission = svc.create_mission("prove single-use")
        svc.activate_mission(mission.id)
        job = svc.record_proposal(
            mission_id=mission.id,
            title="run once",
            executor="fake-executor",
            workspace_paths=("w/",),
            actions=("run_tests",),
            proposed_by=Principal.PLANNER,
        )
        appr = svc.request_approval(job.id)
        svc.decide(appr.id, ApprovalDecision.GRANTED, Principal.HUMAN)

        adapter = FakeExecutor(behavior="success")

        # First dispatch: runs and spends the approval.
        r1 = svc.dispatch(job.id, adapter)
        assert not r1.duplicated, "first dispatch must not be a replay"
        assert len(adapter.invocations) == 1, "expected exactly one run"
        stored = svc.store.get_approval(appr.id)
        assert stored.consumed_at is not None, "approval was not consumed"
        print("PASS 1: first dispatch ran once and consumed the approval")

        # A6 replay of the finished job: idempotent, nothing runs.
        r2 = svc.dispatch(job.id, adapter)
        assert r2.duplicated, "replay of a finished job must be idempotent"
        assert len(adapter.invocations) == 1, "a replay executed the action again"
        print("PASS 2: replay of a finished job executed nothing")

        # Now the real single-use test: put the job back into a dispatchable
        # state and try to spend the same approval a second time.
        svc.store.update_job(job.id, state=JobState.APPROVED)
        try:
            svc.dispatch(job.id, adapter)
        except DispatchRefused as e:
            assert "consumed" in e.reason, f"refused for the wrong reason: {e.reason}"
            assert len(adapter.invocations) == 1, "the action ran a second time"
            print(f"PASS 3: spent approval refused a fresh dispatch ({e.reason})")
        else:
            print("FAIL 3: a spent approval authorised a second execution")
            return 1

        # And the approval is still spent, with a durable audit trail.
        kinds = [e["kind"] for e in svc.store.list_events()]
        assert kinds.count("approval_consumed") == 1, kinds
        print("PASS 4: exactly one approval_consumed event, durable in the log")

        print("PROVEN: single-use holds and a replay executes nothing")
        return 0
    finally:
        svc.close()


if __name__ == "__main__":
    sys.exit(main())
