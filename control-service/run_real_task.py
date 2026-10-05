import logging
from pathlib import Path
from agent_os.store import Store
from agent_os.service import ControlService
from agent_os.adapters.hermes_executor import HermesExecutor
from agent_os.models import Job, Principal, encode_command, JobState

def main():
    logging.basicConfig(level=logging.INFO)
    db_path = Path(".testtmp/real_job.db")
    if db_path.exists(): db_path.unlink()
    db_path.parent.mkdir(exist_ok=True)
    
    store = Store(db_path)
    service = ControlService(store)
    
    # Register hermes executor
    src = Path("/home/mehdi/workspace/wp-bioscentiran")
    executor = HermesExecutor(source_workspace=src, timeout_seconds=120, profile="my-personal-assistant")
    # For hermes_executor, we need to add it to service registry
    service.executors[executor.name] = executor
    print(f"[*] Registered {executor.name} with binary {executor.hermes_binary}")
    
    # 1. Create Mission
    m_id = service.create_mission(title="Real WP-Bioscentiran Theme Task")
    print(f"[*] Mission created: {m_id}")
    
    # 2. Propose Job
    # Command: Create a simple info file in theme folder
    prompt = """Write a php comment header at the top of functions.php in the theme directory to say it is managed by Agent OS. 
Use write_file or patch on D:\DEV-Studio\AI\Hermes-Vault\wp-bioscentiran\theme\Theme\technogene-theme\functions.php, 
but since it is inside WSL, use the absolute UNC path \\wsl.localhost\Ubuntu-26.04\home\mehdi\workspace\wp-bioscentiran\theme\Theme\technogene-theme\functions.php
Wait, just create a new file named `agent-os-trace.txt` inside \\wsl.localhost\Ubuntu-26.04\home\mehdi\workspace\wp-bioscentiran\theme\Theme\technogene-theme\ containing simply Agent
