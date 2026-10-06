"""Mutation check: remove the --user 1000:1000 flag and confirm p6_proof red.

A proof that cannot fail proves nothing. This temporarily removes the
--user 1000:1000 flag (dropping the container to root) from
container_executor.py, runs the proof, and restores
the file byte-for-byte. If the proof still passed, it would be asserting
something the code does for an unrelated reason.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
EXECUTOR = ROOT / "agent_os/adapters/container_executor.py"

# The security flag: runs the command as non-root (p6_proof PASS 9)
FLAG = '''            "--user", "1000:1000",'''

original = EXECUTOR.read_text(encoding="utf-8")
assert FLAG in original, "security flag not found; the proof targets the wrong code"

try:
    # Remove the --user flag (the container then runs as root)
    mutated = original.replace(FLAG, "")
    EXECUTOR.write_text(mutated, encoding="utf-8")
    
    r = subprocess.run([sys.executable, "-B", "p6_proof.py"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    print("--- proof with --user 1000:1000 REMOVED ---")
    print(r.stdout.strip())
    print("exit code:", r.returncode)
    if r.returncode == 0:
        print("\nRESULT: BAD - the proof passed without the guard; it proves nothing")
        sys.exit(1)
    print("\nRESULT: GOOD - the proof fails without the guard, so it is real")
finally:
    EXECUTOR.write_text(original, encoding="utf-8")
    assert EXECUTOR.read_text(encoding="utf-8") == original, "restore failed"
    print("container_executor.py restored byte-for-byte")
