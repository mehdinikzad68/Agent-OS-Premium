import json
from pathlib import Path
from agent_os.store import Store

def main():
    store = Store(Path(".testtmp/dispatch_real3.db"))
    for ev in store.list_events():
        if "completed" in ev.get("kind", ""):
            print("---", ev["kind"], "---")
            payload = ev.get("payload_json", {})
            evidence = payload.get("evidence", {})
            for key, val in evidence.items():
                if key == "hermes_response":
                    print("\n==== STDOUT ====")
                    print(val)
                    print("================")
                elif key == "stdout":
                    pass
                else:
                    print(f"  {key}: {val}")
    store.close()

if __name__ == "__main__":
    main()
