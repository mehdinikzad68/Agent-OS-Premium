import logging
from pathlib import Path
from agent_os.store import Store
from agent_os.service import ControlService
from agent_os.adapters.hermes_executor import HermesExecutor
from agent_os.models import Job, Principal, encode_command, JobState
import os

def main():
    logging.basicConfig(level=logging.INFO)
    db_path = Path("/home/mehdi/workspace/Agent-OS/control-service/.testtmp/real_job.db")
    if db_path.exists(): db_path.unlink()
    db_path.parent.mkdir(exist_ok=True, parents=True)
    
    store = Store(db_path)
    service = ControlService(store)
    
    # Register hermes executor
    src = Path("/home/mehdi/workspace/wp-bioscentiran")
    executor = HermesExecutor(source_workspace=src, timeout_seconds=200, profile="my-personal-assistant")
    # For hermes_executor, we need to add it to service registry
    service.executors[executor.name] = executor
    print(f"[*] Registered {executor.name} with binary {executor.hermes_binary}")
    
    # 1. Create Mission
    m_id = service.create_mission(title="Real WP-Bioscentiran Theme Task")
    print(f"[*] Mission created: {m_id}")
    
    # 2. Propose Job
    # Command: Create a simple info file in theme folder
    prompt = """Create a new file named `agent-os-trace.txt` inside \\\\wsl.localhost\\Ubuntu-26.04\\home\\mehdi\\workspace\\wp-bioscentiran\\theme\\Theme\\technogene-theme\\ containing simply 'Agent OS successfully connected here.' use write_file"""
    
    j_id = service.propose_job(
        mission_id=m_id,
        title="Add trace file",
        executor="hermes-executor",
        workspace_paths=[str(src)],
        actions=["write_file"],
        proposed_by=Principal.PLANNER,
        command=encode_command(["solve", prompt])
    )
    print(f"[*] Job proposed: {j_id}")
    
    # 3. Approve
    a_id = service.request_approval(job_id=j_id)
    service.grant_approval(a_id, Principal.HUMAN)
    print(f"[*] Job approved: {a_id}")
    
    # 4. Dispatch
    print(f"[*] Dispatching job...")
    receipt = service.dispatch(j_id)
    print(f"[*] Dispatch receipt: {receipt}")
    
    job = store.get_job(j_id)
    print(f"[*] Job Outcome State: {job.state}")
    
    # 5. Check trace file
    trace_file = src / "theme/Theme/technogene-theme/agent-os-trace.txt"
    if trace_file.exists():
        print(f"\\n[+] Real task success! Trace file created: {trace_file.read_text()}")
    else:
        print("\\n[-] Failed to create trace file.")

if __name__ == "__main__":
    main()
