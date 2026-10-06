"""Mutation check: disable BOTH single-use guards and confirm p5_proof red.

A proof that cannot fail proves nothing. Since the B1 fix (review
2026-10-05) single-use has two independent guards:

  1. policy check 9 - validate_dispatch refuses a consumed approval;
  2. the dispatch consume gate - spend-before-execute, where the atomic
     UPDATE ... WHERE consumed_at IS NULL actually stops a re-run.

Removing only (1) used to be enough to redden the proof; guard (2) now
catches it, which is defense-in-depth working as designed rather than a
vacuous proof. So this check removes BOTH - and restores both files
byte-for-byte, which is the evidence that nothing stays mutated - and
only then must the proof fail.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
POLICY = ROOT / "agent_os/policy.py"
SERVICE = ROOT / "agent_os/service.py"

CHECK = """    # Check 9: single-use. A consumed approval is dead.
    if approval.consumed_at is not None:
        return "approval_already_consumed"
"""

GATE = ("        if approval is None or not self.store.consume_approval("
        "approval.id, iso(now)):")
GATE_MUTATED = "        if False:  # MUTATED: dispatch consume gate disabled too"

original_policy = POLICY.read_text(encoding="utf-8")
original_service = SERVICE.read_text(encoding="utf-8")
assert CHECK in original_policy, "check 9 not found; the proof targets the wrong code"
assert original_service.count(GATE) == 1, "dispatch consume gate not found exactly once"

try:
    POLICY.write_text(original_policy.replace(CHECK, ""), encoding="utf-8")
    SERVICE.write_text(original_service.replace(GATE, GATE_MUTATED), encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", "p5_proof.py"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    print("--- proof with policy check 9 AND the dispatch gate REMOVED ---")
    print(r.stdout.strip())
    print("exit code:", r.returncode)
    if r.returncode == 0:
        print("\nRESULT: BAD - the proof passed without either guard; "
              "it proves nothing")
        sys.exit(1)
    print("\nRESULT: GOOD - the proof fails without the guards, so it is real")
finally:
    POLICY.write_text(original_policy, encoding="utf-8")
    SERVICE.write_text(original_service, encoding="utf-8")
    assert POLICY.read_text(encoding="utf-8") == original_policy, "policy restore failed"
    assert SERVICE.read_text(encoding="utf-8") == original_service, "service restore failed"
    print("policy.py and service.py restored byte-for-byte")
