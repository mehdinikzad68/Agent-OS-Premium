# -*- coding: utf-8 -*-
"""F7b — the port must be released when serve() fails after binding.

Measured, not assumed: with the server object left open after a post-bind
failure, the port stays held; with server_close() on the failure path, a probe
socket binds and listens successfully. So the port probe IS a valid witness -
and the first version of this test could not tell the two apart, because its
fake class never really bound anything the probe could see.

The bug in the old test: it replaced ThreadingHTTPServer with a wrapper that
returned a subclass whose daemon_threads was a throwing property, and the
resulting socket state was never actually exercised. The wrapper was also
patched onto the module for the whole test, leaking into later tests.

So this version asserts on the real thing: the port.
"""
import os
import pathlib
import socket
import tempfile
import unittest
from unittest import mock

from agent_os import api as api_mod
from agent_os.service import ControlService
from agent_os.store import Store


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _port_is_free(port: int) -> bool:
    """True when nothing holds the port.

    bind() alone is not enough on some platforms, so listen() is included:
    a port that can be bound but not listened on is still occupied.
    """
    t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        t.bind(("127.0.0.1", port))
        t.listen(1)
        return True
    except OSError:
        return False
    finally:
        t.close()


class _Boom(Exception):
    pass


class _FailsOnAssign:
    """Makes `server.daemon_threads = True` raise, inside serve()'s try.

    Raising in the fake's __init__ would escape BEFORE serve()'s try - a
    different path from the one F7b is about. The assignment is the statement
    that has to fail, so this descriptor arms the object and lets serve()'s own
    `try:` see the error.
    """

    def __get__(self, obj, owner=None):
        return False

    def __set__(self, obj, value):
        err = obj.__dict__.get("_aosrv_fail_with")
        if err is not None:
            raise err
        obj.__dict__["daemon_threads"] = value


class ServeReleasesThePortOnFailure(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="f7b-"))
        # ControlService takes a PATH and builds its own Store; passing a
        # Store makes str(db_path) yield its repr, and sqlite then creates
        # a real database named "<agent_os.store.Store object at 0x...>"
        # in the current directory.
        self.svc = ControlService(self.tmp / "s.db")
        # sanity: the probe must be capable of seeing a held port, or every
        # assertion below is vacuous
        held = _free_port()
        keep = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        keep.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        keep.bind(("127.0.0.1", held))
        keep.listen(1)
        self.assertFalse(_port_is_free(held),
                         "the probe cannot detect a held port, so it cannot "
                         "prove one was released")
        keep.close()

    def tearDown(self):
        try:
            self.svc.close()
        except Exception:
            pass
        for suf in ("", "-wal", "-shm"):
            try:
                pathlib.Path(str(self.tmp / "s.db") + suf).unlink()
            except OSError:
                pass
        try:
            self.tmp.rmdir()
        except OSError:
            pass

    def test_the_port_is_released_when_post_bind_setup_fails(self):
        """The real ThreadingHTTPServer binds; only the post-bind line fails."""
        port = _free_port()
        real = api_mod.ThreadingHTTPServer
        created = []
        close_calls = []

        class FailsAfterBind(real):
            daemon_threads = _FailsOnAssign()

            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                created.append(self)
                orig = self.server_close

                def counting_close():
                    close_calls.append(1)
                    orig()
                self.server_close = counting_close
                # daemon_threads is a class-level descriptor here, so the
                # assignment serve() makes INSIDE its try raises there. That
                # is the window the finding is about: raising in __init__
                # would escape before the try and is a different path.
                self.__dict__["_aosrv_fail_with"] = _Boom(
                    "simulated: post-bind setup failed")

        with mock.patch.object(api_mod, "ThreadingHTTPServer", FailsAfterBind):
            with self.assertRaises(_Boom):
                api_mod.serve(self.svc, host="127.0.0.1", port=port,
                              token="t", insecure=False)

        self.assertTrue(created, "the fake server was never constructed, so "
                                 "this test proved nothing")
        # Probe BEFORE any cleanup of our own. The previous version closed the
        # fake servers in the test and only then checked the port, so the
        # check could never fail: it measured the test's cleanup, not the
        # code's. Measured: the port IS still held at this point without the
        # fix, so this ordering is what makes the assertion meaningful.
        try:
            self.assertEqual(len(close_calls), 1,
                             "serve() failed after binding and never closed "
                             "the socket it had already opened")
            self.assertTrue(_port_is_free(port),
                            "serve() failed after binding and left the port held")
        finally:
            for s in created:
                try:
                    s.server_close()
                except OSError:
                    pass

    def test_an_interrupt_after_bind_also_releases_the_port(self):
        port = _free_port()
        real = api_mod.ThreadingHTTPServer
        created = []
        close_calls = []

        class InterruptedAfterBind(real):
            daemon_threads = _FailsOnAssign()

            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                created.append(self)
                orig = self.server_close

                def counting_close():
                    close_calls.append(1)
                    orig()
                self.server_close = counting_close
                # arm the descriptor; the assignment inside serve()'s try
                # raises KeyboardInterrupt there, which is the window under test
                self.__dict__["_aosrv_fail_with"] = KeyboardInterrupt(
                    "simulated: Ctrl-C after bind")

        with mock.patch.object(api_mod, "ThreadingHTTPServer",
                               InterruptedAfterBind):
            with self.assertRaises(KeyboardInterrupt):
                api_mod.serve(self.svc, host="127.0.0.1", port=port,
                              token="t", insecure=False)

        try:
            self.assertEqual(len(close_calls), 1,
                             "a Ctrl-C between bind and the caller left the "
                             "socket open; only `except Exception` would miss it")
            self.assertTrue(_port_is_free(port))
        finally:
            for s in created:
                try:
                    s.server_close()
                except OSError:
                    pass

    def test_a_successful_serve_still_binds_and_returns(self):
        port = _free_port()
        srv = api_mod.serve(self.svc, host="127.0.0.1", port=port,
                            token="t", insecure=False)
        try:
            self.assertTrue(srv.daemon_threads)
            self.assertEqual(srv.server_address[1], port)
            self.assertFalse(_port_is_free(port),
                             "a running server must hold its port")
        finally:
            srv.server_close()
        self.assertTrue(_port_is_free(port), "server_close() did not release it")

    def test_refusing_without_a_token_never_binds(self):
        port = _free_port()
        with self.assertRaises(api_mod.ApiError):
            api_mod.serve(self.svc, host="127.0.0.1", port=port,
                          token=None, insecure=False)
        self.assertTrue(_port_is_free(port),
                        "a refused start still bound the port")


if __name__ == "__main__":
    unittest.main()
