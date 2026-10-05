import logging
from pathlib import Path
from agent_os.store import Store
from agent_os.service import ControlService
from agent_os.adapters.hermes_executor import HermesExecutor
from agent_os.models import Principal, ApprovalDecision

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    # Use a persistent db for the control service
    db = Path(".logs/agent_os_kanban.db")
    db.parent.mkdir(exist_ok=True)
    
    store = Store(db)
    service = ControlService(store)
    
    src = Path("/home/mehdi/workspace/wp-bioscentiran")
    # Setup Hermes Executor. Profiling my-personal-assistant to ensure the environment is correct.
    executor = HermesExecutor(source_workspace=src, timeout_seconds=180, profile="my-personal-assistant")
    
    mission = service.create_mission(title="Implement [current_year] shortcode in wp-bioscentiran")
    
    prompt = """Please modify the file theme/Theme/technogene-theme/functions.php in the workspace to add a simple WordPress shortcode. 
Add the following snippet at the end of the file:

// AgentOS: Added current_year shortcode
add_shortcode('current_year', function() {
    return date('Y');
});

DO NOT GUESS THE PATH, just use the relative path theme/Theme/technogene-theme/functions.php as your workspace is already set."""
    
    job = service.record_proposal(
        mission_id=mission.id,
        title="Add current_year shortcode",
        executor="hermes-executor",
        workspace_paths=(str(src),),
        actions=("delegate_task",),
        proposed_by=Principal.PLANNER,
        command=["solve", prompt]
    )
    
    print(f"[*] Mission ID: {mission.id}")
    print(f"[*] Job ID: {job.id}")
    
    approval = service.request_approval(job_id=job.id)
    service.decide(approval_id=approval.id, decision=ApprovalDecision.GRANTED, principal=Principal.HUMAN)
    print(f"[*] Approval granted for {job.id}")

    print(f"[*] Dispatching {job.id} via HermesExecutor. This will take a moment...")
    try:
        r = service.dispatch(job_id=job.id, adapter=executor)
        print(f"[*] Receipt:\n{r.model_dump_json(indent=2)}")
    except Exception as e:
        print(f"[!] Failed to execute job: {e}")
        import traceback
        traceback.print_exc()
    finally:
        service.close()

if __name__ == '__main__':
    main()
