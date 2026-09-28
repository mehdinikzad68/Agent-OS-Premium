# -*- coding: utf-8 -*-
"""F5 proof over real HTTP.

Measured before the fix: a symlink in the source workspace caused copytree's
default (symlinks=False) to copy the TARGET's contents into the run directory.
A command could then read them, and the executor publishes stdout in evidence,
so /api/jobs/<id>/evidence returned the contents over HTTP:

    innocent_link/id_rsa      PRIVATE KEY MATERIAL
    innocent_link/credentials password=hunter2

A proof that only asserted "the run was refused" would pass on any error, so it
witnesses two SEPARATE things and needs both:

  1. on the real code the job is refused AND the secret text appears nowhere in
     the response body
  2. with the guard removed, the secret text appears in /evidence

Run it twice, the way f1_proof.py does: PROVEN, then NOT PROVEN.
"""
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

D = pathlib.Path(__file__).resolve().parent
SECRET = "PRIVATE KEY MATERIAL"
CREDS = "password=hunter2"


def log(m):
    print(m, flush=True)


def call(base, token, method, path, payload=None):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body or "{}")
        except json.JSONDecodeError:
            return e.code, {"raw": body[:2000]}


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="f5proof-"))
    outside = tmp / "outside"
    outside.mkdir()
    (outside / "id_rsa").write_text(SECRET + "\n", encoding="utf-8")
    (outside / "credentials").write_text(CREDS + "\n", encoding="utf-8")

    ws = tmp / "workspace"
    ws.mkdir()
    (ws / "app.py").write_text("print('hello from the workspace')\n",
                               encoding="utf-8")
    # a name that gives no hint about what it points at - this is the shape
    # that made the leak easy to miss in review
    os.symlink(str(outside), str(ws / "shared"))

    db = tmp / "f5.db"
    token = "f5-proof-token"
    port = "8831"
    # POST /api/projects does not accept a scope field (api.py:247-252), so
    # the allowed root can only come from AGENT_OS_PROJECT_SCOPE.
    env = dict(os.environ, AGENT_OS_TOKEN=token,
               AGENT_OS_PROJECT_SCOPE=str(tmp))
    # the server leads its own session so cleanup takes the whole group
    proc = subprocess.Popen(
        [sys.executable, "-B", "-m", "agent_os.cli", "serve",
         "--host", "127.0.0.1", "--port", port,
         "--db", str(db), "--sandbox-root", str(tmp / "sandboxes"),
         "--source-workspace", str(ws),
         # the subprocess adapter is off unless asked for; without this the
         # dispatch is refused as unknown_executor and the proof would be
         # measuring an unrelated error
         "--enable-subprocess"],
        cwd=D, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/status", timeout=2)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.2)
        else:
            out = proc.stdout.read() if proc.stdout else ""
            log("server never became ready:\n" + out[-2000:])
            return 2

        log("1. a symlink named 'shared' points outside the workspace")
        log("   and the real target holds an id_rsa and a credentials file")

        # scope is explicit: the temp workspace must sit inside it, or
        # register_project refuses the root before anything else is checked
        st, proj = call(base, token, "POST", "/api/projects", {
            "name": "f5", "root": str(ws), "environment": "wsl",
        })
        if st >= 400:
            log(f"   project rejected: {st} {proj}")
            return 2
        log(f"2. project registered at the workspace root (HTTP {st})")

        argv = [sys.executable, "-c",
                "print(open('shared/credentials').read().strip())"]
        st, job = call(base, token, "POST", "/api/jobs", {
            "mission_id": "m-f5", "title": "read through the link",
            # the registered name is "subprocess-executor" (cli.py), not
            # "subprocess" - a wrong name fails as unknown_executor, which
            # looks like a refusal but measures nothing
            "executor": "subprocess-executor", "command": argv,
            "workspace_paths": [str(ws)], "actions": ["run_command"],
        })
        if st >= 400:
            log(f"   job rejected: {st} {job}")
            return 2
        jid = job["id"]
        log(f"3. job {jid} created, asking to read shared/credentials")

        st, appr = call(base, token, "POST", "/api/approvals", {"job_id": jid})
        if st >= 400:
            log(f"4. approval request failed: {st} {appr}")
            return 2
        # requesting an approval is not granting it; dispatch refuses with
        # approval_not_granted:requested until the decision is recorded
        st, dec = call(base, token, "POST",
                       f"/api/approvals/{appr['id']}/decide",
                       {"decision": "granted"})
        log(f"4. approval requested then granted (HTTP {st})")
        if st >= 400:
            log(f"   {dec}")
            return 2

        st, disp = call(base, token, "POST", f"/api/jobs/{jid}/dispatch", {})
        log(f"5. dispatch -> HTTP {st}")
        body = json.dumps(disp)
        if st >= 400:
            log(f"   {body[:400]}")
        else:
            log("   dispatch accepted the job; whether the command actually ran")
            log("   is decided by the final state and by what evidence contains")

        st, final = call(base, token, "GET", f"/api/jobs/{jid}")
        log(f"6. final state: {final.get('state')}")
        for k in ("error", "result", "reason"):
            if final.get(k):
                log(f"   {k}: {str(final[k])[:300]}")

        st, ev = call(base, token, "GET", f"/api/jobs/{jid}/evidence")
        evidence = json.dumps(ev)
        log(f"7. evidence endpoint -> HTTP {st}, {len(evidence)} bytes")
        log(f"   evidence as returned: {evidence[:400]}")
        # A proof that watches only for the secret would also pass if the
        # command never ran for an unrelated reason. Require positive evidence
        # that THIS mechanism is what carried or withheld the content.
        marker = "hello from the workspace"
        log(f"   the workspace's own file mentions {marker!r}: "
            f"{marker in evidence}")

        log("")
        leaks = [name for name, needle in (("id_rsa", SECRET),
                                           ("credentials", CREDS)) if needle in evidence]
        if SECRET in body or CREDS in body:
            leaks.append("dispatch response")

        # WorkerLostError maps to interrupted_unknown (models.py:126-128): the
        # worker may have had an effect, so it is never auto-marked successful.
        # That IS the refusal for this finding - a "worker_lost" state name
        # does not exist, and asserting one would make the proof unreachable.
        state = final.get("state")
        refused = state == "interrupted_unknown"

        if leaks:
            log("NOT PROVEN - outside content reached the client:")
            for n in leaks:
                log(f"   LEAK: {n}")
            log(f"   final state was: {final.get('state')}")
            return 1

        if not refused:
            log("NOT PROVEN - nothing leaked, but the run was not refused "
                "either; this proof would pass on an unrelated error.")
            log(f"   state: {final.get('state')}")
            log(f"   error: {str(final.get('error'))[:300]}")
            return 1

        log("PROVEN")
        log("   - the run was refused, with the offending path named")
        log("   - the secret appears nowhere in the dispatch response")
        log("   - the secret appears nowhere in the evidence endpoint")
        return 0
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
