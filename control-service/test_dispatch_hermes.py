import logging
import json
from pathlib import Path
from agent_os.store import Store
from agent_os.service import ControlService
from agent_os.adapters.hermes_executor import HermesExecutor
from agent_os.models import Principal, ApprovalDecision

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    db = Path(".testtmp/dispatch_real4.db")
    if db.exists(): db.unlink()
    db.parent.mkdir(exist_ok=True)
    
    store = Store(db)
    service = ControlService(store)
    
    src = Path("/home/mehdi/workspace/wp-bioscentiran")
    executor = HermesExecutor(source_workspace=src, timeout_seconds=180, profile="my-personal-assistant")
    
    mission = service.create_mission(title="Direct Dispatch Task 4")
    
    prompt = """Please modify the file `README.md` in the current workspace. Append the line `\n\n## Managed by Agent OS\nThis workspace is now connected via HermesExecutor.` to the end of the file. DO NOT GUESS THE PATH, just use the current directory `./README.md` or `README.md` since your workspace is already set appropriately via --in."""
    
    job = service.record_proposal(
        mission_id=mission.id,
        title="modify README using Hermes",
        executor="hermes-executor",
        workspace_paths=(str(src),),
        actions=("delegate_task",),
        proposed_by=Principal.PLANNER,
        command=["solve", prompt]
    )
    
    approval = service.request_approval(job_id=job.id)
    service.decide(approval_id=approval.id, decision=ApprovalDecision.GRANTED, principal=Principal.HUMAN)
    
    print(f"[*] Dispatching {job.id} with HermesExecutor")
    r = service.dispatch(job_id=job.id, adapter=executor)
    print(f"[*] Receipt: {r}")
    
    service.close()

if __name__ == "__main__":
    main()
