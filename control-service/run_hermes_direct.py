import logging
from pathlib import Path
from agent_os.store import Store
from agent_os.service import ControlService
from agent_os.adapters.hermes_executor import HermesExecutor
from agent_os.models import Job, Principal, JobState
from agent_os.api import register_executor

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    db_path = Path(".testtmp/real_job.db")
    if db_path.exists(): db_path.unlink()
    db_path.parent.mkdir(exist_ok=True)
    
    store = Store(db_path)
    service = ControlService(store)
    
    # Instantiate and register manually bypassing the CLI
    src = Path("/home/mehdi/workspace/wp-bioscentiran")
    executor = HermesExecutor(source_workspace=src, timeout_seconds=120, profile="my-personal-assistant")
    
    # Register the executor inside the API registry (wait, ControlService does not hold executors!)
    # Actually, ControlService does dispatch via HTTP API? NOT in direct call if we use validate_dispatch.
    # WAIT! `service.dispatch` does not execute it! `service.dispatch` looks up the executor in `agent_os.api`!
    # Let\s
