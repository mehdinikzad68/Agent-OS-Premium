#!/usr/bin/env python3
"""F8 proof on a REAL HTTP server: propose -> approve -> dispatch a real
command, and show the subprocess actually ran.

This is deliberately separate from the unit tests. The unit tests prove the
encode/decode contract; this proves the whole chain works over the wire with
the real server process, the real sqlite file, and a real interpreter child
process - the exact path that was 100% broken before (F8: every argv list died
with "type 'list' is not supported").

Run from control-service/:
    python f8_proof.py

Exit 0 = proven. Any failure exits non-zero with a clear message.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULT = HERE / "f8-proof-result.txt"
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
    finish(False, "NOT PROVEN - F8 is not fixed end to end")


def call(base: str, token: str, method: str, path: str, body=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
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
    """Poll the real status route with the real token. A bare socket connect
    would succeed before the router is mounted, which is exactly the kind of
    race that makes a proof script lie."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                base + "/api/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="f8-proof-"))
    src = tmp / "src"
    src.mkdir()
    (src / "marker.txt").write_text("original", encoding="utf-8")
    (src / "calc.py").write_text(
        "print('7 tests passed')\n", encoding="utf-8"
    )

    db = tmp / "proof.db"
    token = "f8-proof-token"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))  # kernel-chosen (T4): never a fixed port
        port = str(_s.getsockname()[1])
    env = dict(os.environ, AGENT_OS_TOKEN=token)
    # --enable-subprocess + --source-workspace is the ONLY way the subprocess
    # adapter gets registered. Without both, dispatch would be refused with
    # unknown_executor and the proof would be vacuous.
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
            fail(f"server never became ready. output:\n{out.decode('utf-8', 'replace')[:2000]}")

        st, ex = call(base, token, "GET", "/api/executors")
        log(f"0. registered executors: {ex}")
        if "subprocess-executor" not in (ex or {}).get("executors", []):
            fail(f"the subprocess executor is not registered: {ex}")

        # --- 1. mission ------------------------------------------------
        st, mission = call(base, token, "POST", "/api/missions", {"title": "F8 proof"})
        if st not in (200, 201):
            fail(f"creating the mission returned {st}: {mission}")
        mid = mission["id"]
        log(f"1. mission created over HTTP: {mid}")

        # --- 2. propose a REAL argv list (this is what used to 500) ----
        argv = [sys.executable, "calc.py"]
        st, job = call(base, token, "POST", "/api/jobs", {
            "mission_id": mid,
            "title": "run the real proof command",
            "executor": "subprocess-executor",
            "workspace_paths": [str(src)],
            "actions": ["run_command", "run_tests"],
            "proposed_by": "planner",
            "command": argv,
        })
        if st not in (200, 201):
            fail(f"proposing with a real argv list returned {st}: {job}\n"
                 f"Before the fix this step died with "
                 f"ProgrammingError: type 'list' is not supported.")
        jid = job["id"]
        log(f"2. proposal accepted with argv={argv}")
        log(f"   job.command as returned by the API: {job.get('command')!r}")
        if job.get("command") != argv:
            fail(f"the API did not return the argv it was given: {job.get('command')!r}")

        # --- 3. the row really is TEXT in sqlite -----------------------
        import sqlite3
        conn = sqlite3.connect(str(db))
        raw = conn.execute("SELECT typeof(command), command FROM jobs WHERE id=?",
                           (jid,)).fetchone()
        conn.close()
        log(f"3. sqlite typeof(command)={raw[0]!r} value={raw[1]!r}")
        if raw[0] != "text":
            fail(f"command is stored as {raw[0]}, not text - the encoding is not applied")

        # --- 4. no approval yet: dispatch must be refused -------------
        st, body = call(base, token, "POST", f"/api/jobs/{jid}/dispatch", {})
        log(f"4. dispatch without approval returned {st} (must not be 2xx)")
        if st < 400:
            fail(f"dispatch without approval returned {st} - enforcement regressed")

        # --- 5. approve, then dispatch for real ------------------------
        st, appr = call(base, token, "POST", "/api/approvals", {"job_id": jid})
        if st not in (200, 201):
            fail(f"requesting approval returned {st}: {appr}")
        aid = appr["id"]
        st, dec = call(base, token, "POST", f"/api/approvals/{aid}/decide",
                       {"decision": "granted"})
        if st not in (200, 201):
            fail(f"granting approval returned {st}: {dec}")
        log(f"5. approval granted (only HUMAN may decide)")

        # --- 6. dispatch: a REAL interpreter runs ---------------------
        st, receipt = call(base, token, "POST", f"/api/jobs/{jid}/dispatch", {})
        log(f"6. dispatch returned {st}: {json.dumps(receipt)[:400]}")
        if st >= 400:
            fail(f"dispatch failed with {st}: {receipt}")

        # --- 7. the outcome must be real, not fabricated --------------
        st, final = call(base, token, "GET", f"/api/jobs/{jid}")
        state = (final or {}).get("state")
        log(f"7. final job state: {state}")
        log(f"   job keys: {sorted((final or {}).keys())}")
        st, evbody = call(base, token, "GET", f"/api/jobs/{jid}/evidence")
        log(f"   evidence endpoint returned {st}")
        blob = json.dumps(final) + json.dumps(evbody)
        log(f"   evidence keys: "
            f"{sorted(evbody.keys()) if isinstance(evbody, dict) else evbody}")
        if "7 tests passed" not in blob:
            fail(f"the child's own output never reached the API. Body:\n{blob[:2000]}")
        log("   the child's stdout ('7 tests passed') is present in the API response")
        if state not in ("completed_verified", "completed_unverified",
                         "dispatched", "running"):
            fail(f"unexpected final state {state}")

        # --- 8. the source workspace was NOT modified -----------------
        if (src / "marker.txt").read_text(encoding="utf-8") != "original":
            fail("the live source workspace was modified - the disposable-copy "
                 "rule was broken")
        log("8. the live source workspace is untouched (disposable copy only)")

        finish(True, "PROVEN - a real argv list was stored, dispatched, and a real "
                     "subprocess ran and reported back over HTTP")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
