"""F3 proof over REAL HTTP: a timeout must leave no process behind.

The lesson from F1 applies here. A proof that only exercises the happy path
cannot go red, so this one has to be able to fail. Step 3 below asserts the
grandchild is dead, and this script is run twice by its driver: once on the
real code (must be PROVEN) and once with start_new_session removed
(must be NOT PROVEN).

The command is submitted through the public API and dispatched by the service,
so what is measured is the whole path an operator's approval actually takes -
not a direct call into the executor.
"""
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
RESULT = HERE / "f3-proof-result.txt"
LINES = []


def log(msg):
    LINES.append(msg)
    print(msg, flush=True)


def finish(ok, verdict):
    log("")
    log(verdict)
    RESULT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    sys.exit(0 if ok else 1)


def fail(msg):
    log("FAIL: " + msg)
    finish(False, "NOT PROVEN - F3 is not fixed end to end")


def call(base, token, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def wait_ready(base, token, timeout=30.0):
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


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="f3-proof-"))
    src = tmp / "src"
    src.mkdir()
    (src / "calc.py").write_text("print('9 tests passed')\n", encoding="utf-8")

    # The grandchild stamps this file forever. If it is still stamping after
    # the API reports the timeout, the process tree survived.
    marker = tmp / "alive.marker"
    stamp = (
        "import time,pathlib\n"
        f"p = pathlib.Path({str(marker)!r})\n"
        "for i in range(100000):\n"
        "    p.write_text(str(i))\n"
        "    time.sleep(0.05)\n"
    )
    argv = [sys.executable, "-c",
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable,'-c',{stamp!r}])\n"
            "print('9 tests passed', flush=True)\n"
            "time.sleep(100000)\n"]

    db = tmp / "f3.db"
    token = "f3-proof-token"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))  # kernel-chosen (T4): never a fixed port
        port = str(_s.getsockname()[1])
    env = dict(os.environ, AGENT_OS_TOKEN=token)
    # The server gets its OWN session. Without this, when the fix is absent
    # the executor's os.killpg has no separate group to target and can signal
    # the harness itself - the proof would die before it could report the leak
    # instead of reporting it.
    proc = subprocess.Popen(
        [sys.executable, "-B", "-m", "agent_os.cli", "serve",
         "--db", str(db), "--port", port, "--insecure",
         "--enable-subprocess", "--source-workspace", str(src),
         "--subprocess-timeout", "3"],
        cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True)
    base = f"http://127.0.0.1:{port}"

    try:
        if not wait_ready(base, token):
            fail("the server never became ready")
        log("0. server up, subprocess executor enabled")

        st, mission = call(base, token, "POST", "/api/missions",
                           {"title": "F3 proof"})
        if st not in (200, 201):
            fail(f"mission returned {st}: {mission}")
        mid = mission["id"]

        st, job = call(base, token, "POST", "/api/jobs", {
            "mission_id": mid, "title": "a command that never finishes",
            "executor": "subprocess-executor", "workspace_paths": [str(src)],
            "actions": ["run_command"], "proposed_by": "planner",
            "command": argv})
        if st not in (200, 201):
            fail(f"proposal returned {st}: {job}")
        jid = job["id"]
        log(f"1. job {jid} carries a command that spawns a grandchild")

        st, appr = call(base, token, "POST", "/api/approvals", {"job_id": jid})
        if st not in (200, 201):
            fail(f"approval request returned {st}: {appr}")
        st, dec = call(base, token, "POST",
                       f"/api/approvals/{appr['id']}/decide",
                       {"decision": "granted"})
        if st not in (200, 201):
            fail(f"granting returned {st}: {dec}")
        log("2. approved and granted like any other job")

        t0 = time.time()
        try:
            st, receipt = call(base, token, "POST", f"/api/jobs/{jid}/dispatch", {})
        except Exception as e:
            # With the fix absent the executor can signal this proof's own
            # group and the server dies mid-dispatch. Say so plainly instead
            # of letting a truncated run look like an unproven one.
            fail(f"the server stopped answering during dispatch ({type(e).__name__}). "
                 f"With start_new_session removed, killpg targets the wrong "
                 f"group and the service is killed - which is itself the defect.")
        el = time.time() - t0
        st2, final = call(base, token, "GET", f"/api/jobs/{jid}")
        log(f"3. dispatch returned {st} after {el:.1f}s, state={final['state']}")
        if el > 25:
            fail(f"the timeout never engaged - dispatch took {el:.1f}s")

        # The job-level state is completed_unverified; the REASON lives in the
        # evidence. Assert on the reason, not on the state name - the state is
        # shared with an ordinary command that produced no test report.
        st3, ev = call(base, token, "GET", f"/api/jobs/{jid}/evidence")
        if "timeout" not in json.dumps(ev):
            fail(f"expected a timeout in the evidence, got: {json.dumps(ev)[:300]}")
        log("   the evidence records reason=timeout, not success")
        if final["state"] == "completed_verified":
            fail("a timed-out command was reported as VERIFIED")

        # THE defect, measured over HTTP: does the grandchild outlive the call?
        time.sleep(1.0)
        if not marker.exists():
            fail("the grandchild never started - nothing was measured")
        before = marker.read_text(encoding="utf-8")
        time.sleep(1.5)
        after = marker.read_text(encoding="utf-8")
        still_running = before != after
        log(f"4. marker after the timeout: {before} -> {after} over 1.5s")
        log(f"   the grandchild is STILL RUNNING: {still_running}")
        if still_running:
            fail("a grandchild survived the timeout - the process group was "
                 "not killed. The API said 'timeout' while the work continued.")

        # and no orphan is left holding the marker
        ps = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True,
                            text=True, timeout=20).stdout
        orphans = [ln for ln in ps.splitlines() if str(marker) in ln]
        log(f"5. processes still holding the marker: {len(orphans)}")
        if orphans:
            fail(f"orphans survived: {orphans}")

        log("   the timeout is still reported as a timeout, not as success")

        finish(True, "PROVEN - a timeout kills the whole process group, the API "
                     "reports it honestly, and nothing is left running")
    finally:
        # the server leads its own session, so take the whole group with it
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        # never leave the stamping grandchild behind, whatever happened above
        try:
            for ln in subprocess.run(["ps", "-eo", "pid,args"],
                                     capture_output=True, text=True,
                                     timeout=20).stdout.splitlines():
                if str(marker) in ln:
                    pid = int(ln.split()[0])
                    if pid != os.getpid():
                        os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


if __name__ == "__main__":
    import signal  # noqa: E402  (used in the finally cleanup)
    main()
