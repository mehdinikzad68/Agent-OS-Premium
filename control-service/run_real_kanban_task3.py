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
    
    mission = service.create_mission(title="Direct implementation via Terminal")
    
    prompt = """You are an automated coding assistant. Please use the 'terminal' tool to run this exact bash command in the current directory:

echo -e "\n// ADDED BY AGENT OS TEST\nfunction __tg_current_year() { return date('Y'); }\nadd_shortcode('current_year', '__tg_current_year');" >> theme/Theme/technogene-theme/functions.php

Do not use write_file or patch or other tools. Just use the terminal tool. Verify with tail -n 5 theme/Theme/technogene-theme/functions.php and then stop."""
    
    job = service.record_proposal(
        mission_id=mission.id,
        title="Add current_year via Terminal",
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
