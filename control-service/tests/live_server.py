# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Shared helpers for the suites that boot a real ``agent_os.cli serve``.

The bug this removes
--------------------
Each live suite used to hard-code a port (8873, 8877, 8878, 8893, 8894, 8898)
and wait for ``/api/status`` to answer. That readiness probe cannot tell
*whose* server answered. When a run is killed mid-suite (Ctrl-C, timeout,
crash) its child server survives as an orphan and keeps the port. The next
run's own child fails to bind, but the probe still succeeds against the
orphan, so the suite silently talks to a stale server with a stale database.
The visible symptoms were a baffling ``added 0 != 3`` / ``skipped 3`` in the
ingest suite and ``Connection refused`` in the tool suite, neither of which
reproduced in isolation.

Two properties remove the class of bug, not one instance:

1. The port is chosen by the kernel, not by the test. ``--port 0`` makes the
   OS hand out a free port; the CLI prints the real one, which we parse. Two
   suites can no longer collide, and an orphan cannot steal the port because
   the port it holds is not the one we asked for.
2. Readiness is proven against our own child. We wait for the banner line on
   the child's stdout, then confirm ``/api/status`` reports the database we
   handed it. A foreign server on that port fails the db_path check, so the
   failure is loud instead of silent.

The child runs in its own session (``start_new_session=True``) and is killed
by process group, so a timeout or crash leaves no descendants behind.

Note there is deliberately no "reap leftover servers" helper: a pattern that
matches this test server's command line also matches an operator's real
``agent-os serve``, so an automatic reaper would kill live work. The port-0
scheme makes reaping unnecessary.
"""
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

D = pathlib.Path(__file__).resolve().parent.parent
_BANNER = re.compile(r"http://127\.0\.0\.1:(\d+)")


def boot_server(token, prefix="agent-os-test-", db_name="agent-os.db",
                extra_args=(), timeout=40.0, env_extra=None):
    """Start ``agent_os.cli serve`` on an OS-chosen port.

    Returns a dict: proc, base, port, tmp, db, token. Pass it to
    ``stop_server`` (or ``restart_server``) when done. Raises AssertionError
    with the child's own words if it never announces a port or never becomes
    ready.
    """
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
    db = tmp / db_name
    return _spawn(tmp, db, token, extra_args, timeout, env_extra)


def _spawn(tmp, db, token, extra_args, timeout, env_extra=None):
    env = dict(os.environ, AGENT_OS_TOKEN=token, PYTHONUNBUFFERED="1")
    if env_extra:
        env.update(env_extra)
    argv = [
        sys.executable, "-u", "-B", "-m", "agent_os.cli", "serve",
        "--host", "127.0.0.1", "--port", "0", "--db", str(db),
    ] + list(extra_args)
    proc = subprocess.Popen(
        argv, cwd=str(D), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)

    # The banner is printed only after the socket is bound, so it is both the
    # readiness signal and the source of the real port.
    deadline = time.time() + timeout
    port = None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise AssertionError(
                    f"server exited before announcing a port (rc={proc.returncode})")
            continue
        m = _BANNER.search(line)
        if m:
            port = int(m.group(1))
            break
    if port is None:
        _kill(proc)
        raise AssertionError("server did not announce a port in time")

    srv = {"proc": proc, "tmp": tmp, "db": db, "port": port,
           "base": f"http://127.0.0.1:{port}", "token": token}
    _await_ready(srv, deadline)
    return srv


def _await_ready(srv, deadline):
    """Confirm the server answering is OURS, not a leftover orphan."""
    while time.time() < deadline:
        try:
            st, body = call(srv, "GET", "/api/status")
            if st == 200:
                info = json.loads(body)
                if info.get("db_path") == str(srv["db"]):
                    return
                raise AssertionError(
                    f"port {srv['port']} is served by a foreign process: "
                    f"db_path={info.get('db_path')!r}, expected {str(srv['db'])!r}")
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.1)
    _kill(srv["proc"])
    raise AssertionError("server never became ready")


def call(srv, method, path, body=None, token=None, timeout=30):
    """One HTTP call against a booted server. Returns (status, text).

    Never raises on 4xx/5xx; those come back as (code, body). ``token=None``
    means "use the server's token"; pass ``token=False`` to send no
    Authorization header at all.
    """
    tok = srv["token"] if token is None else token
    headers = {}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        srv["base"] + path, method=method, headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _kill(proc):
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass


def stop_server(srv, remove_tmp=True):
    """Kill the child and (by default) delete its scratch directory."""
    if srv is None:
        return
    _kill(srv.get("proc"))
    srv["proc"] = None
    if remove_tmp and srv.get("tmp") is not None:
        import shutil
        shutil.rmtree(srv["tmp"], ignore_errors=True)
        srv["tmp"] = None


def restart_server(srv, token=None, extra_args=(), timeout=40.0):
    """Kill the child and start a fresh one against the SAME database.

    This is what makes a durability claim measurable: the caller asks the new
    process about state the old one wrote.
    """
    tmp, db = srv["tmp"], srv["db"]
    tok = srv.get("token") if token is None else token
    _kill(srv.get("proc"))
    return _spawn(tmp, db, tok, extra_args, timeout)
