#!/usr/bin/env python3
"""F1 proof on a real HTTP server: what the human is SHOWN when granting.

Separate from the unit tests on purpose. The unit tests prove the policy
function compares commands; this proves the decision surface actually carries
the command to the person who clicks, over the wire, from a real server
process reading a real database.

Three things must hold, in this order:
  1. the approval response NAMES the command, as argv
  2. a body-supplied scope.command is ignored, and the attempt is recorded
  3. a job with a command cannot be dispatched under a scope that omits it,
     and the executor is never reached

Run from control-service/. Exit 0 = proven.
"""
from __future__ import annotations

import json
import os
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULT = HERE / "f1-proof-result.txt"
_log: list[str] = []


def log(msg: str) -> None:
    print(msg)
    _log.append(msg)


def finish(ok: bool, verdict: str) -> None:
    RESULT.write_text("\n".join(_log) + f"\nVERDICT: {verdict}\n", encoding="utf-8")
    print(f"\n{verdict}")
    sys.exit(0 if ok else 1)


def fail(msg: str) -> None:
    log(f"FAIL: {msg}")
    finish(False, "NOT PROVEN - F1 is not fixed end to end")


def call(base: str, token: str, method: str, path: str, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def wait_ready(base: str, token: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                base + "/api/status", headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="f1-proof-"))
    src = tmp / "src"
    src.mkdir()
    (src / "marker.txt").write_text("original", encoding="utf-8")
    (src / "calc.py").write_text("print('9 tests passed')\n", encoding="utf-8")

    db = tmp / "f1.db"
    token = "f1-proof-token"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))  # kernel-chosen (T4): never a fixed port
        port = str(_s.getsockname()[1])
    env = dict(os.environ, AGENT_OS_TOKEN=token)
    proc = subprocess.Popen(
        [sys.executable, "-B", "-m", "agent_os.cli", "serve",
         "--db", str(db), "--port", port, "--insecure",
         "--enable-subprocess", "--source-workspace", str(src)],
        cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        if not wait_ready(base, token):
            out = b""
            if proc.poll() is not None and proc.stdout:
                out = proc.stdout.read()
            fail(f"server never became ready:\n{out.decode('utf-8', 'replace')[:1500]}")

        st, mission = call(base, token, "POST", "/api/missions",
                           {"title": "F1 proof"})
        if st not in (200, 201):
            fail(f"mission returned {st}: {mission}")
        mid = mission["id"]
        log(f"0. mission {mid}")

        # --- 1. the approval NAMES the command ------------------------
        argv = [sys.executable, "calc.py"]
        st, job = call(base, token, "POST", "/api/jobs", {
            "mission_id": mid, "title": "run the real command",
            "executor": "subprocess-executor", "workspace_paths": [str(src)],
            "actions": ["run_tests"], "proposed_by": "planner", "command": argv,
        })
        if st not in (200, 201):
            fail(f"proposal returned {st}: {job}")
        jid = job["id"]
        st, appr = call(base, token, "POST", "/api/approvals", {"job_id": jid})
        if st not in (200, 201):
            fail(f"approval request returned {st}: {appr}")
        scope = appr["scope"]
        log(f"1. scope as the human receives it: {json.dumps(scope)}")
        if "command" not in scope:
            fail("the approval scope has no `command` key - this is the F1 defect")
        if scope["command"] != argv:
            fail(f"the scope shows {scope['command']!r}, the job runs {argv!r}")
        log(f"   the command IS visible, as argv: {scope['command']}")
        log("   BEFORE the fix this scope had only executor/workspace_paths/actions,")
        log("   so a grant meant 'run_tests in /w' with the effect being whatever")
        log("   argv the job carried - a decision made blind.")

        # --- 2. a body-supplied command is ignored --------------------
        st, job2 = call(base, token, "POST", "/api/jobs", {
            "mission_id": mid, "title": "second", "executor": "subprocess-executor",
            "workspace_paths": [str(src)], "actions": ["run_tests"],
            "proposed_by": "planner", "command": ["echo", "attacker-chosen"],
        })
        st, appr2 = call(base, token, "POST", "/api/approvals", {
            "job_id": job2["id"],
            "scope": {
                "executor": "subprocess-executor",
                "workspace_paths": [str(src)],
                "actions": ["run_tests"],
                "command": ["echo", "attacker-chosen"],
            },
        })
        if st not in (200, 201):
            fail(f"second approval returned {st}: {appr2}")
        st, evs = call(base, token, "GET", "/api/events")
        # The route wraps the list: {"events": [...]}
        rows = (evs or {}).get("events", evs if isinstance(evs, list) else [])
        kinds = [e["kind"] for e in rows]
        log(f"2b. scope.command stored as: {appr2['scope']['command']!r}")
        log(f"    (the job's own command, not the body's - as designed)")
        log(f"   the ignored attempt is in the event stream: "
            f"{'approval.scope_command_ignored' in kinds}")
        if "approval.scope_command_ignored" not in kinds:
            fail("the ignored body command left no trace in /api/events")
        log("   approval.scope_command_ignored is in /api/events - an operator")
        log("   reading the event stream can see the attempt.")

        # --- 3. the happy path still runs a real subprocess -----------
        st, dec = call(base, token, "POST",
                       f"/api/approvals/{appr['id']}/decide", {"decision": "granted"})
        if st not in (200, 201):
            fail(f"granting returned {st}: {dec}")
        st, receipt = call(base, token, "POST", f"/api/jobs/{jid}/dispatch", {})
        if st >= 400:
            fail(f"dispatch of an honestly-approved job failed: {st} {receipt}")
        st, final = call(base, token, "GET", f"/api/jobs/{jid}")
        log(f"3. honestly approved job dispatched: state={final['state']}")
        st, ev = call(base, token, "GET", f"/api/jobs/{jid}/evidence")
        if "9 tests passed" not in json.dumps(ev):
            fail(f"the child never ran. evidence:\n{json.dumps(ev)[:1500]}")
        log("   the real subprocess ran and its stdout reached the API")
        if final["state"] != "completed_verified":
            fail(f"unexpected state {final['state']}")
        if (src / "marker.txt").read_text(encoding="utf-8") != "original":
            fail("the live workspace was modified")
        log("   the live workspace is untouched")

        # --- 4. a grant that no longer names the job's command is refused
        # Steps 1-3 only ever dispatched an HONESTLY approved job. That left a
        # real hole in this proof: with policy.py's command check replaced by
        # `if False`, every step above still passed and the proof still said
        # PROVEN. A proof that cannot go red is not evidence.
        #
        # The job below is approved, granted, and then its STORED scope is
        # rewritten to name a different command - the row a confused writer or
        # a pre-fix insert would leave. The manifest hash still matches,
        # because the job did not change, so the refusal can only come from
        # F1's own check.
        st, mission4 = call(base, token, "POST", "/api/missions",
                            {"title": "F1 tampered grant"})
        mid4 = mission4["id"]
        st, job4 = call(base, token, "POST", "/api/jobs", {
            "mission_id": mid4, "title": "grant that will be tampered with",
            "executor": "subprocess-executor", "workspace_paths": [str(src)],
            "actions": ["run_tests"], "proposed_by": "planner",
            "command": [sys.executable, "calc.py"]})
        jid4 = job4["id"]
        st, appr4 = call(base, token, "POST", "/api/approvals", {"job_id": jid4})
        st, dec4 = call(base, token, "POST",
                        f"/api/approvals/{appr4['id']}/decide",
                        {"decision": "granted"})
        if st not in (200, 201):
            fail(f"granting job4 returned {st}: {dec4}")

        con = sqlite3.connect(str(db))
        row = con.execute("SELECT scope_json FROM approvals WHERE id=?",
                          (appr4["id"],)).fetchone()
        if row is None:
            fail(f"no stored approval row for {appr4['id']}")
        scope4 = json.loads(row[0])
        scope4["command"] = json.dumps([sys.executable, "attacker.py"],
                                       separators=(",", ":"))
        con.execute("UPDATE approvals SET scope_json=? WHERE id=?",
                    (json.dumps(scope4), appr4["id"]))
        con.commit()
        con.close()
        log(f"4. stored scope now names: {scope4['command']}")
        log(f"   while the job's own command is: "
            f"{json.dumps([sys.executable, 'calc.py'])}")

        st, refused = call(base, token, "POST", f"/api/jobs/{jid4}/dispatch", {})
        log(f"   dispatch of the tampered grant returned {st}: "
            f"{json.dumps(refused)[:200] if not isinstance(refused, str) else refused[:200]}")
        if st < 400:
            fail(f"a grant naming a DIFFERENT command was accepted: "
                 f"{st} {json.dumps(refused)[:300] if not isinstance(refused, str) else refused[:300]}")
        if "command_not_in_scope" not in json.dumps(refused):
            fail(f"refused, but not by the command check: {refused}")
        log("   REFUSED with command_not_in_scope - the check that this proof")
        log("   exists to prove actually fired. Removing it lets this job run.")

        finish(True, "PROVEN - the human's approval names the command, a "
                     "body-supplied command is ignored and recorded, a grant "
                     "whose command was changed is refused, and a real "
                     "subprocess still runs end to end")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
