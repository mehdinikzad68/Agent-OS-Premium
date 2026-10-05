import logging
from pathlib import Path

from agent_os.adapters.hermes_executor import HermesExecutor
from agent_os.models import Job, JobState, Principal, encode_command

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    src = Path("/mnt/c/Users/Mehdi/AppData/Local/Temp/scratch_agent_os")
    src.mkdir(parents=True, exist_ok=True)
    
    (src / "readme.txt").write_text("Init test")

    executor = HermesExecutor(
        source_workspace=src,
        timeout_seconds=180, profile="my-personal-assistant",
    )

    print(f"[*] Initialized HermesExecutor with binary: {executor.hermes_binary}")

    command = ["solve", "Create a new file named 'hello.txt' inside the workspace ($HERMES_KANBAN_WORKSPACE, which is passed via --in) and write 'Hermes connected successfully!' in it."]

    job = Job(
        id="job-integration-01",
        mission_id="mission-01",
        title="Integration test",
        proposed_by=Principal.PLANNER,
        executor="hermes-executor",
        workspace_paths=("/workspace",),
        actions=("delegate_task",),
        state=JobState.APPROVED,
        attempt_no=0,
        manifest_hash="test",
        created_at="now",
        updated_at="now",
        command=encode_command(command),
    )

    print(f"[*] Running job {job.id}...")
    outcome = executor.run(job, 1)

    print("\n--- OUTCOME ---")
    print(f"Status: {outcome.status}")
    print("Evidence:")
    for key, val in outcome.evidence.items():
        if key == "stdout":
            pass
        else:
            print(f"  {key}: {val}")
            if key == "hermes_response":
                print("\n==== STDOUT ====")
                print(val)
                print("================")

    # Check disk
    hello_file = src / "hello.txt"
    if hello_file.exists():
        print(f"\n[+] Success! hello.txt exists with content: {hello_file.read_text()}")
    else:
        print("\n[-] hello.txt was not created in the source workspace.")
        
if __name__ == "__main__":
    main()
