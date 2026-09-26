"""End-to-end product verification: starts the real server via the CLI,
drives a complete mission lifecycle over HTTP, and verifies enforcement.

Run from control-service/:
    python e2e_verify.py [python_executable]

Exit 0 = product verified. Any failure exits non-zero with a clear message.
Writes a step-by-step log to e2e-result.txt (sandbox-friendly).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULT = HERE / "e2e-result.txt"

_steps: list[str] = []


def log(msg: str) -> None:
    print(msg)
    _steps.append(msg)


def fail(msg: str) -> None:
    log(f"FAIL: {msg}")
    RESULT.write_text("\n".join(_steps) + "\nRESULT: FAIL\n", encoding="utf-8")
    sys.exit(1)


def main() -> int:
    py = sys.executable
    token = "e2e-verification-token"
    db_dir = HERE / ".testtmp" / "e2e"
    db_dir.mkdir(parents=True, exist_ok=True)
    db = db_dir / "e2e.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            p.unlink()

    # Start the real server via the CLI module.
    port = "8533"
    cmd = [
        py, "-m", "agent_os.cli", "serve",
        "--db", str(db),
        "--host", "127.0.0.1", "--port", port,
        "--token", token,
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(HERE),
        stdout=open(db_dir / "server.log", "wb"),
        stderr=subprocess.STDOUT,
    )
    time.sleep(2.0)
    if proc.poll() is not None:
        fail("server process exited during startup; see server.log")

    base = "http://127.0.0.1:8533"

    def req(method: str, path: str, body=None, tok=token):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(base + path, data=data, method=method)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        if tok:
            r.add_header("Authorization", f"Bearer {tok}")
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        # 1. UI is served
        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read()
        if b"Agent OS" not in html:
            fail("UI not served at /")
        log("step 1 ok: UI served at /")

        # 2. auth fails closed
        s, _ = req("GET", "/api/status", tok=None)
        if s != 401:
            fail(f"expected 401 without token, got {s}")
        s, _ = req("GET", "/api/status", tok="wrong")
        if s != 401:
            fail(f"expected 401 with wrong token, got {s}")
        log("step 2 ok: auth fail-closed (401)")

        # 3. status
        s, st = req("GET", "/api/status")
        if s != 200 or st.get("name") != "agent-os":
            fail(f"status failed: {s} {st}")
        log(f"step 3 ok: status version={st['version']} executors={st['executors']}")

        # 4. mission lifecycle
        s, m = req("POST", "/api/missions", {"title": "e2e mission"})
        if s != 201:
            fail(f"mission create failed: {s} {m}")
        mid = m["id"]
        s, m = req("POST", f"/api/missions/{mid}/activate")
        if s != 200 or m["state"] != "active":
            fail(f"activate failed: {s} {m}")
        log("step 4 ok: mission created + activated")

        # 5. job + approval + grant
        s, j = req("POST", "/api/jobs", {
            "mission_id": mid, "title": "e2e job",
            "executor": "fake-executor",
            "workspace_paths": ["w/"], "actions": ["read_file", "run_tests"],
            "proposed_by": "planner",
        })
        if s != 201:
            fail(f"job propose failed: {s} {j}")
        jid = j["id"]
        s, a = req("POST", "/api/approvals", {"job_id": jid})
        if s != 201 or a["decision"] != "requested":
            fail(f"approval request failed: {s} {a}")
        s, d = req("POST", f"/api/approvals/{a['id']}/decide", {"decision": "granted"})
        if s != 200 or d["decision"] != "granted":
            fail(f"decide failed: {s} {d}")
        log("step 5 ok: proposed -> approval requested -> granted by human")

        # 6. dispatch -> verified
        s, r = req("POST", f"/api/jobs/{jid}/dispatch")
        if s != 200 or r["receipt"]["final_state"] != "completed_verified":
            fail(f"dispatch failed: {s} {r}")
        log("step 6 ok: dispatched -> completed_verified")

        # 7. duplicate dispatch is idempotent
        s, r2 = req("POST", f"/api/jobs/{jid}/dispatch")
        if s != 200 or not r2["receipt"]["duplicated"]:
            fail(f"duplicate dispatch not idempotent: {s} {r2}")
        log("step 7 ok: duplicate dispatch idempotent")

        # 8. dispatch without approval is refused (new job)
        s, j2 = req("POST", "/api/jobs", {
            "mission_id": mid, "title": "unapproved",
            "executor": "fake-executor",
            "workspace_paths": ["w/"], "actions": ["read_file"],
        })
        s, rr = req("POST", f"/api/jobs/{j2['id']}/dispatch")
        if s != 409:
            fail(f"unapproved dispatch should be 409, got {s} {rr}")
        log("step 8 ok: unapproved dispatch refused (409, before execution)")

        # 9. events audited
        s, ev = req("GET", "/api/events")
        kinds = [e["kind"] for e in ev["events"]]
        for expected in ("mission_created", "approval_granted", "dispatched",
                         "job_completed_verified", "dispatch_denied"):
            if expected not in kinds:
                fail(f"missing audit event {expected} in {kinds}")
        log(f"step 9 ok: audit trail complete ({len(kinds)} events)")

        # 10. restart durability: kill server, restart, state survives
        proc.terminate()
        proc.wait(timeout=10)
        proc2 = subprocess.Popen(
            cmd, cwd=str(HERE),
            stdout=open(db_dir / "server2.log", "wb"),
            stderr=subprocess.STDOUT,
        )
        time.sleep(2.0)
        try:
            s, j3 = req("GET", f"/api/jobs/{jid}")
            if s != 200 or j3["state"] != "completed_verified":
                fail(f"state lost after restart: {s} {j3}")
            s, ev2 = req("GET", "/api/events")
            if len(ev2["events"]) != len(ev["events"]):
                fail("event history changed after restart")
            log("step 10 ok: restart durability verified")

            # 11. durable evidence survives the restart
            s, evd = req("GET", f"/api/jobs/{jid}/evidence")
            if s != 200 or not evd.get("evidence") or not evd["evidence"].get("test_report"):
                fail(f"evidence not durable across restart: {s} {evd}")
            log("step 11 ok: evidence persisted and served after restart")
        finally:
            proc2.terminate()
            proc2.wait(timeout=10)

        RESULT.write_text("\n".join(_steps) + "\nRESULT: PASS\n", encoding="utf-8")
        log("E2E PASS — product verified end-to-end")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
