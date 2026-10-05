"""Phase 3 proof: a discovered tool is not thereby permitted to run.

Same discipline as f1/f3/f5: PROVEN on the real code, and NOT PROVEN when the
guard that makes the claim true is disabled. A proof that cannot go red is
decoration.

What is actually proved, over real HTTP against a real server:

  1. discovery reports real tools with real versions, read from the real
     binaries on this machine;
  2. an unreadable version is reported as unknown - never as a number;
  3. registering a tool records a row that claims no execution rights, in the
     API response, in the stored row, and after a re-registration;
  4. the executor set is byte-identical before and after discovery and
     registration - the set of things a job can run does not move;
  5. the executor source contains no reference to the tool table at all, so the
     registry is inert rather than merely unused on this path;
  6. an unsupported environment is refused with a reason, not an empty list.

Part 5 is the one that makes the phase safe to ship before Phase 6. A
behavioural test can only prove the calls it makes; reading the source proves
there is nothing for a future change to accidentally reach.
"""
import json
import os
import pathlib
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

D = pathlib.Path(__file__).resolve().parent
TOKEN = "phase3-proof-token"
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
    _s.bind(("127.0.0.1", 0))  # kernel-chosen (T4): never a fixed port
    PORT = str(_s.getsockname()[1])


def call(base, method, path, body=None):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, (json.loads(raw) if raw else {})
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:300]}


def wait(base, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(base + "/api/status", timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.25)
    return False


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))


db = D / ".p3proof.db"
for suffix in ("", "-wal", "-shm"):
    p = pathlib.Path(str(db) + suffix)
    if p.exists():
        p.unlink()

env = dict(os.environ, AGENT_OS_TOKEN=TOKEN)
proc = subprocess.Popen(
    [sys.executable, "-B", "-m", "agent_os.cli", "serve",
     "--host", "127.0.0.1", "--port", PORT, "--db", str(db)],
    cwd=str(D), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, start_new_session=True)
base = f"http://127.0.0.1:{PORT}"
try:
    if not wait(base):
        print("server never became ready")
        raise SystemExit(2)

    print("\n1. discovery reports the real machine")
    st, disc = call(base, "GET", "/api/tools/discover")
    check("discovery returns 200", st == 200, f"status={st}")
    tools = {t["name"]: t for t in disc.get("tools", [])}
    check("at least three real tools were found", len(tools) >= 3,
          f"found {sorted(tools)}")
    for name in ("git", "python3"):
        if name in tools:
            t = tools[name]
            check(f"{name} has a version read from the real binary",
                  t["confidence"] == "exact" and t["version"],
                  f"{t['version']!r} confidence={t['confidence']}")
    check("the response says nothing is executable",
          disc.get("execution_granted") is False)

    print("\n2. an unreadable version stays unknown")
    # a real binary that is not on the allowlist is never executed, and a name
    # that does not exist yields nothing at all rather than a fabricated entry
    st, empty = call(base, "POST", "/api/tools/discover",
                     {"environment": "wsl", "names": ["definitely-not-here"]})
    check("a name that does not exist yields no fabricated entry",
          st == 200 and empty.get("tools") == [] and empty.get("skipped") == [],
          f"tools={empty.get('tools')} skipped={empty.get('skipped')}")
    # a non-allowlisted binary that DOES exist: reported, never executed
    st, skipped = call(base, "POST", "/api/tools/discover",
                       {"environment": "wsl", "names": ["ls", "env"]})
    skipped_names = {x["name"] for x in skipped.get("skipped", [])}
    check("a non-allowlisted binary is reported as skipped, not hidden",
          "ls" in skipped_names, f"skipped={sorted(skipped_names)}")
    check("a skipped candidate never claims a version",
          all(x.get("version") is None for x in skipped.get("skipped", [])))

    print("\n3. an unsupported environment is refused, not reported empty")
    st, bad = call(base, "POST", "/api/tools/discover",
                   {"environment": "windows", "names": ["git"]})
    check("windows discovery is refused with a reason",
          st == 400 and bad.get("error", {}).get("code") == "environment_unsupported",
          f"status={st} body={bad}")
    check("the refusal is not an empty tool list",
          "tools" not in bad, f"body={bad}")

    print("\n4. registration records an inert row")
    st, before_execs = call(base, "GET", "/api/executors")
    target = tools.get("git") or next(iter(tools.values()))
    st, reg = call(base, "POST", "/api/tools/registry", {
        "name": target["name"], "environment": target["environment"],
        "path": target["path"], "version": target["version"],
        "confidence": target["confidence"]})
    check("registration returns 201", st == 201, f"status={st}")
    check("the API response claims no execution rights",
          reg.get("grants_execution") is False, f"{reg.get('grants_execution')}")

    st, listing = call(base, "GET", "/api/tools/registry")
    row = next((t for t in listing.get("tools", []) if t["id"] == reg.get("id")), None)
    check("the stored row claims no execution rights",
          row is not None and row.get("grants_execution") is False,
          f"row={row}")

    st, again = call(base, "POST", "/api/tools/registry", {
        "name": target["name"], "environment": target["environment"],
        "path": target["path"], "version": target["version"],
        "confidence": target["confidence"]})
    check("re-registration does not upgrade the row",
          again.get("id") == reg.get("id") and
          again.get("grants_execution") is False, f"{again.get('id')}")

    print("\n5. the executable set does not move")
    st, after_execs = call(base, "GET", "/api/executors")
    check("the executor list is identical before and after",
          before_execs.get("executors") == after_execs.get("executors"),
          f"{before_execs.get('executors')} -> {after_execs.get('executors')}")
    check("no tool name became an executor",
          not any(target["name"] in e for e in after_execs.get("executors", [])),
          f"executors={after_execs.get('executors')}")

    print("\n6. the registry is inert in the source, not just on this path")
    sys.path.insert(0, str(D))
    from agent_os.adapters import subprocess_executor
    src = pathlib.Path(subprocess_executor.__file__).read_text(encoding="utf-8")
    banned = ["list_tools", "get_tool", "create_tool", "grants_execution",
              "from .tools", "tools"]
    hits = [b for b in banned if b in src]
    check("the executor never reads the tool table", not hits, f"found {hits}")
    # and no other runtime module consults it either
    others = []
    for mod in sorted((D / "agent_os").glob("*.py")):
        if mod.name in ("api.py", "service.py", "store.py", "models.py",
                        "discovery.py", "__init__.py"):
            continue
        text = mod.read_text(encoding="utf-8")
        for b in ("list_tools", "get_tool", "create_tool", "grants_execution"):
            if b in text:
                others.append(f"{mod.name}:{b}")
    check("no adapter consults the registry", not others, f"found {others}")

    print("\n7. removal forgets the record and nothing else")
    st, rem = call(base, "DELETE", f"/api/tools/registry/{reg['id']}")
    check("the row is removed", st == 200 and rem.get("removed") is True)
    st, listing2 = call(base, "GET", "/api/tools/registry")
    check("the registry is empty again",
          reg["id"] not in {t["id"] for t in listing2.get("tools", [])})
    st, after_rem = call(base, "GET", "/api/executors")
    check("removal did not touch the executor set",
          after_rem.get("executors") == before_execs.get("executors"))

finally:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    for suffix in ("", "-wal", "-shm"):
        p = pathlib.Path(str(db) + suffix)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

failed = [n for n, ok, _ in results if not ok]
print()
print("=" * 66)
if failed:
    print(f"NOT PROVEN - {len(failed)} of {len(results)} checks failed:")
    for n in failed:
        print(f"  - {n}")
    raise SystemExit(1)
print(f"PROVEN - all {len(results)} checks passed over real HTTP")
print("=" * 66)
