"""Anti-proof: the Phase 3 proof must be able to fail.

Same rule as F1/F3/F5 - a proof that stays green when the guard is removed is
not evidence. Two independent ways this claim could quietly break:

  A. the registry starts granting execution: grants_execution flips to True
  B. the executor starts consulting the tool table

Both are valid edits. Neither may produce a syntax error - a broken file is not
a behavioural demonstration, and treating one as evidence has been the single
most common false proof in this project.
"""
import pathlib
import re
import shutil
import subprocess
import sys

D = pathlib.Path("/home/mehdi/workspace/Agent-OS/control-service")
API = D / "agent_os" / "api.py"
MODELS = D / "agent_os" / "models.py"
EXEC = D / "agent_os" / "adapters" / "subprocess_executor.py"

pristine = {p: p.read_text(encoding="utf-8") for p in (API, MODELS, EXEC)}


def run_proof():
    r = subprocess.run([sys.executable, "-u", "-B", "p3_proof.py"],
                       cwd=D, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


base_rc, base_out = run_proof()
print(f"real code -> exit {base_rc}: "
      f"{'PROVEN' if base_rc == 0 else 'NOT PROVEN'}")
if base_rc != 0:
    print(base_out[-1500:])
    raise SystemExit("the proof does not hold on the real code; stop here")

MUTATIONS = [
    ("A1 the registry claims it grants execution",
     MODELS, "    grants_execution: bool = False", "    grants_execution: bool = True"),
    ("A2 the model's serialiser reports the row as executable",
     MODELS, '            "grants_execution": self.grants_execution,',
     '            "grants_execution": True,'),
    ("A2b the API invents a second, contradictory value",
     API, '        return tool.to_dict() if hasattr(tool, "to_dict") else dict(tool)',
     '        d = tool.to_dict() if hasattr(tool, "to_dict") else dict(tool)\n'
     '        d["grants_execution"] = False\n        return d'),
    ("A3 the executor consults the tool table",
     EXEC, "import json", "import json\n\n\ndef _peeks_at_tools(self):  # mutant\n"
     "    return self.service.store.list_tools()"),
]

print()
print("=" * 70)
print("each mutation must make the proof go red, for a behavioural reason")
print("=" * 70)

ok_mutations = []
for label, target, old, new in MUTATIONS:
    text = pristine[target]
    if old not in text:
        print(f"  ANCHOR MISS  {label}")
        continue
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    try:
        rc, out = run_proof()
    finally:
        target.write_text(pristine[target], encoding="utf-8")

    if re.search(r"SyntaxError|IndentationError|NameError", out):
        verdict = "BROKEN    <-- invalid experiment, not evidence"
    elif rc != 0:
        failed = re.findall(r"^\s+- (.+)$", out, re.M)
        verdict = f"red ({len(failed)} check(s) failed)"
        if failed:
            verdict += f": {failed[0][:56]}"
        ok_mutations.append(label)
    else:
        verdict = "STILL GREEN  <-- the proof cannot detect this"
    print(f"  {verdict:52} {label}")

print()
print("=" * 70)
files_clean = all(p.read_text(encoding="utf-8") == pristine[p] for p in pristine)
print(f"all source files restored: {files_clean}")
print(f"mutations that turned the proof red: {len(ok_mutations)}/{len(MUTATIONS)}")
print("=" * 70)
raise SystemExit(0 if (ok_mutations and files_clean) else 1)
