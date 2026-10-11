# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

# -*- coding: utf-8 -*-
"""F7 — two resource leaks that a failed startup leaves behind.

store.py: the sqlite connection is opened, then several statements run, then
_init_schema(). Measured before the fix: a failing _init_schema left the
connection open, and because __init__ never returned, the caller had no handle
to close it with.

api.py: ThreadingHTTPServer binds the socket inside its own constructor, so
from that line the port is taken. A raise before the caller receives the
server leaves it bound, and the next start reports "address already in use"
for no visible reason.

The witness in both cases is the RESOURCE, not the exception: a test that only
asserts "it raised" passes on code that leaks. So these count open file
descriptors before and after.
"""

import os
import pathlib
import shutil
import socket
import sqlite3
import tempfile
import unittest
from unittest import mock

from agent_os import api as api_mod
from agent_os import store as store_mod


def _fds_under(path: str) -> int:
    """How many of this process's open fds point at something under `path`."""
    n = 0
    real = os.path.realpath(path)
    try:
        entries = os.listdir("/proc/self/fd")
    except OSError:
        return 0
    for fd in entries:
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue
        if target.startswith(real):
            n += 1
    return n


def _can_a_port_be_rebound(port: int) -> bool:
    """True when nothing else holds the port — the practical leak test."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class StoreDoesNotLeakTheConnection(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f7-store-"))
        self.db = self.tmp / "s.db"

    def tearDown(self):
        for suf in ("", "-wal", "-shm"):
            p = pathlib.Path(str(self.db) + suf)
            try:
                p.unlink()
            except OSError:
                pass
        self.tmp.rmdir()

    def test_a_schema_failure_does_not_leak_the_connection(self):
        before = _fds_under(str(self.tmp))
        with mock.patch.object(store_mod.Store, "_init_schema",
                               side_effect=sqlite3.DatabaseError("simulated")):
            with self.assertRaises(sqlite3.DatabaseError):
                store_mod.Store(self.db)
        after = _fds_under(str(self.tmp))
        self.assertEqual(after, before,
                         f"the failed Store() left {after - before} handle(s) open")

    def test_a_pragma_failure_does_not_leak_the_connection(self):
        # The failure before _init_schema: a corrupt or unreadable file fails
        # at the first PRAGMA, which is the more common startup failure.
        before = _fds_under(str(self.tmp))
        with mock.patch.object(store_mod.sqlite3, "connect",
                               wraps=store_mod.sqlite3.connect) as real:
            real.return_value = mock.MagicMock()
            real.return_value.execute.side_effect = (
                sqlite3.DatabaseError("simulated: not a database"))
            with self.assertRaises(sqlite3.DatabaseError):
                store_mod.Store(self.db)
        after = _fds_under(str(self.tmp))
        self.assertEqual(after, before,
                         "a PRAGMA failure left the connection open")
        # and the close must have been called on the connection we handed out
        self.assertTrue(
            real.return_value.close.called,
            "the connection was never closed on the failure path")

    def test_an_interrupt_during_init_does_not_leak_either(self):
        # KeyboardInterrupt is not an Exception, so an `except Exception`
        # would miss it — and a Ctrl-C during startup is the realistic case.
        before = _fds_under(str(self.tmp))
        with mock.patch.object(store_mod.Store, "_init_schema",
                               side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                store_mod.Store(self.db)
        after = _fds_under(str(self.tmp))
        self.assertEqual(after, before,
                         "an interrupt during init leaked the connection")

    def test_a_successful_store_still_works(self):
        s = store_mod.Store(self.db)
        try:
            s.conn.execute("SELECT 1")
        finally:
            s.close()
        self.assertTrue(self.db.exists())

    def test_the_close_on_failure_is_itself_guarded(self):
        # If close() raises while we are already handling a failure, the
        # original error must still be the one that propagates.
        with mock.patch.object(store_mod.Store, "_init_schema",
                               side_effect=sqlite3.DatabaseError("original")):
            with mock.patch.object(store_mod.sqlite3, "connect",
                                   wraps=store_mod.sqlite3.connect) as real:
                real.return_value = mock.MagicMock()
                real.return_value.execute.side_effect = (
                    sqlite3.DatabaseError("original"))
                real.return_value.close.side_effect = sqlite3.ProgrammingError(
                    "close also failed")
                with self.assertRaises(sqlite3.DatabaseError) as ctx:
                    store_mod.Store(self.db)
        self.assertIn("original", str(ctx.exception),
                      "a failing close masked the real startup error")


class ServeDoesNotLeakTheSocket(unittest.TestCase):
    def _service(self):
        """A service on a throwaway db, and a cleanup the caller must run.

        ControlService takes a PATH and builds its own Store. Passing a Store
        here made str(db_path) yield the repr, so sqlite created a real
        database named "<agent_os.store.Store object at 0x...>" in the current
        directory - 438 of them, none ignored by git.
        """
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="f7-svc-"))
        from agent_os.service import ControlService
        return ControlService(tmp / "s.db"), tmp

    def test_a_failure_after_bind_releases_the_port(self):
        svc, tmp = self._service()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        try:
            svc.close()
        except Exception:
            pass
        port = _free_port()

        # daemon_threads is a plain attribute, so force the assignment to fail
        # the way a real post-bind error would.
        class Boom(Exception):
            pass

        real_server_cls = api_mod.ThreadingHTTPServer
        # Patch the CLASS for the duration of this one call and restore it in
        # a cleanup. Leaving daemon_threads as a property on the real class
        # leaks into every later test in the process - which is what happened
        # the first time, and it looked like a bug in the fix.
        self.addCleanup(setattr, real_server_cls, "daemon_threads",
                        real_server_cls.daemon_threads)

        def make_and_break(*a, **kw):
            srv = real_server_cls(*a, **kw)
            # make the post-bind step raise
            real_server_cls.daemon_threads = property(
                lambda self: True,
                lambda self, v: (_ for _ in ()).throw(Boom("simulated")))
            return srv

        with mock.patch.object(api_mod, "ThreadingHTTPServer", make_and_break):
            with self.assertRaises(Boom):
                api_mod.serve(svc, host="127.0.0.1", port=port,
                              token="t", insecure=False)

        # the port must be free again
        self.assertTrue(
            _can_a_port_be_rebound(port),
            "serve() raised after binding and left the port held")

    def test_a_successful_serve_still_returns_a_usable_server(self):
        svc, tmp = self._service()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        port = _free_port()
        srv = api_mod.serve(svc, host="127.0.0.1", port=port,
                            token="t", insecure=False)
        try:
            self.assertTrue(srv.daemon_threads)
            self.assertEqual(srv.server_address[1], port)
        finally:
            srv.server_close()
            try:
                svc.close()
            except Exception:
                pass

    def test_refusing_without_a_token_never_binds_at_all(self):
        svc, tmp = self._service()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        try:
            with self.assertRaises(api_mod.ApiError):
                api_mod.serve(svc, host="127.0.0.1", port=_free_port(),
                              token=None, insecure=False)
        finally:
            try:
                svc.close()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
