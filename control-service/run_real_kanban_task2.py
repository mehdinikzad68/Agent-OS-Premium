import logging
from pathlib import Path
from agent_os.store import Store
from agent_os.service import ControlService
from agent_os.adapters.hermes_executor import HermesExecutor
from agent_os.models import Principal, ApprovalDecision

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    db = Path(".logs/agent_os_kanban.db")
    store = Store(db)
    service = ControlService(store)
    
    src = Path("/home/mehdi/workspace/wp-bioscentiran")
    executor = HermesExecutor(source_workspace=src, timeout_seconds=180, profile="my-personal-assistant")
    
    mission = service.create_mission(title="Implement current_year shortcode securely")
    
    prompt = """You are an automated coding assistant. Please use the patch or write_file tool to add the following snippet to the END of theme/Theme/technogene-theme/functions.php:

// ADDED BY AGENT OS TEST
function __tg_current_year() { return date('Y'); }
add_shortcode('current_year', '__tg_current_year');

You MUST actually use the tool to change the file. Do not just reply with text. Verify that the file has been modified before ending your turn. The file path is theme/Theme/technogene-theme/functions.php in the current workspace."""
    
    job = service.record_proposal(
        mission_id=mission.id,
        title="Add current_year via tool",
        executor="hermes-executor",
        workspace_paths=(str(src),),
        actions=("delegate_task",),
        proposed_by=Principal.PLANNER,
        command=["solve", prompt]
    )
    
    approval = service.request_approval(job_id=job.id)
    service.decide(approval_id=approval.id, decision=ApprovalDecision.GRANTED, principal=Principal.HUMAN)
    print(f"[*] Dispatching {job.id} via HermesExecutor...")
    try:
        r = service.dispatch(job_id=job.id, adapter=executor)
        print(f"[*] Receipt:\n{r}")
    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        service.close()

if __name__ == '__main__':
    main()
