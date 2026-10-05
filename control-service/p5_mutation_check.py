"""Mutation check: remove policy check 9 and confirm p5_proof.py goes red.

A proof that cannot fail proves nothing. This temporarily removes the
consumed-approval check from policy.py, runs the proof, and restores the file
byte-for-byte. If the proof still passed, it would be asserting something the
code does for an unrelated reason.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
POLICY = ROOT / "agent_os/policy.py"

CHECK = """    # Check 9: single-use. A consumed approval is dead.
    if approval.consumed_at is not None:
        return "approval_already_consumed"
"""

original = POLICY.read_text(encoding="utf-8")
assert CHECK in original, "check 9 not found; the proof targets the wrong code"

try:
    POLICY.write_text(original.replace(CHECK, ""), encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", "p5_proof.py"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    print("--- proof with check 9 REMOVED ---")
    print(r.stdout.strip())
    print("exit code:", r.returncode)
    if r.returncode == 0:
        print("\nRESULT: BAD - the proof passed without the guard; it proves nothing")
        sys.exit(1)
    print("\nRESULT: GOOD - the proof fails without the guard, so it is real")
finally:
    POLICY.write_text(original, encoding="utf-8")
    assert POLICY.read_text(encoding="utf-8") == original, "restore failed"
    print("policy.py restored byte-for-byte")
