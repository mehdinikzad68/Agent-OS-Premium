"""CLI wiring tests: the fail-closed startup rules and the subprocess gate.

These call cmd_serve directly with parsed args — it returns BEFORE opening a
server on every rejected path, so no sockets or threads are involved.
"""

from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from agent_os.cli import build_parser, cmd_serve

TMP = pathlib.Path(__file__).resolve().parent.parent / ".testtmp"


class CliGateTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = str(TMP / "cli.db")
        for suffix in ("", "-wal", "-shm"):
            p = pathlib.Path(self.db + suffix)
            if p.exists():
                p.unlink()
        self.env = mock.patch.dict("os.environ", {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def _args(self, extra):
        return build_parser().parse_args(["serve", "--db", self.db] + extra)

    def test_serve_refuses_without_token(self):
        """fail-closed: no --token, no AGENT_OS_TOKEN, no --insecure => exit 2."""
        rc = cmd_serve(self._args([]))
        self.assertEqual(rc, 2)

    def test_subprocess_gate_requires_source_workspace(self):
        """--enable-subprocess without --source-workspace fails closed (exit 2)
        BEFORE any server starts."""
        rc = cmd_serve(self._args(["--token", "t", "--enable-subprocess"]))
        self.assertEqual(rc, 2)

    def test_non_loopback_host_fails_closed(self):
        """M3: --host 0.0.0.0 exits 2 before any socket is opened."""
        rc = cmd_serve(self._args(["--token", "t", "--host", "0.0.0.0"]))
        self.assertEqual(rc, 2)

    def test_parser_exposes_all_documented_flags(self):
        args = self._args([
            "--insecure", "--port", "9999", "--host", "127.0.0.1",
            "--fake-behavior", "missing_evidence",
            "--enable-subprocess", "--source-workspace", "src",
            "--sandbox-root", "sb", "--subprocess-timeout", "5", "--keep-sandbox",
        ])
        self.assertTrue(args.insecure)
        self.assertEqual(args.port, 9999)
        self.assertEqual(args.fake_behavior, "missing_evidence")
        self.assertTrue(args.enable_subprocess)
        self.assertEqual(args.source_workspace, "src")
        self.assertEqual(args.subprocess_timeout, 5)
        self.assertTrue(args.keep_sandbox)


if __name__ == "__main__":
    unittest.main()
