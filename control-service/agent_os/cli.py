"""Command-line entry point for Agent OS.

Usage:
    agent-os serve --db PATH [--host 127.0.0.1] [--port 8470] [--token TOKEN] [--insecure]
    agent-os token                       # print a fresh random bearer token
    agent-os init --db PATH              # initialize (create) the database
    agent-os test                        # run the enforcement test suite

Token resolution order for `serve`:
    1. --token argument
    2. AGENT_OS_TOKEN environment variable
    3. (refuse to start) unless --insecure is passed

Fail-closed: serving without a token is an error unless --insecure is
explicitly given (test/dev only).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .logging_setup import configure, get_logger, log_event, register_secret
from .models import utc_now
from .service import ControlService
from .api import serve, register_executor, generate_token
from .adapters.fake import FakeExecutor

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8470


def _resolve_token(args) -> str | None:
    if args.token:
        return args.token
    return os.environ.get("AGENT_OS_TOKEN")


def cmd_serve(args) -> int:
    _log = get_logger("cli")
    log_file = configure()
    token = _resolve_token(args)
    # The live bearer token is not a static string in the source, so pattern
    # matching cannot catch it. Registering it is what makes it unmaskable.
    register_secret(token)
    if token is None and not args.insecure:
        print("refusing to serve without a token. set AGENT_OS_TOKEN, pass --token, or --insecure", file=sys.stderr)
        return 2

    service = ControlService(args.db)
    # Only the fake executor is registered by default. Real adapters are
    # registered ONLY when explicitly enabled by an operator decision.
    register_executor("fake-executor", FakeExecutor(behavior=args.fake_behavior))
    log_event(
        _log,
        logging.INFO,
        "service.start",
        db=str(args.db),
        host=args.host,
        port=args.port,
        auth="token" if token else "INSECURE",
        subprocess_executor=bool(args.enable_subprocess),
        log_file=str(log_file) if log_file else None,
    )

    # Gated: the subprocess executor runs real OS commands in a disposable
    # copy of a source workspace. It requires an explicit, separate opt-in
    # (--enable-subprocess + --source-workspace) and its own sandbox root.
    if args.enable_subprocess:
        from pathlib import Path

        if not args.source_workspace:
            print("--enable-subprocess requires --source-workspace", file=sys.stderr)
            service.close()
            return 2
        from .adapters.subprocess_executor import SubprocessExecutor

        sandbox_root = args.sandbox_root or (Path(args.db).parent / "sandboxes")
        register_executor(
            "subprocess-executor",
            SubprocessExecutor(
                source_workspace=args.source_workspace,
                timeout_seconds=args.subprocess_timeout,
                keep_workspace=args.keep_sandbox,
                sandbox_root=sandbox_root,
            ),
        )
        print(
            f"subprocess executor ENABLED (source={args.source_workspace}, "
            f"timeout={args.subprocess_timeout}s, sandbox_root={sandbox_root})"
        )

    server = serve(service, host=args.host, port=args.port, token=token, insecure=args.insecure)
    host, port = server.server_address[:2]
    print(f"agent-os serving on http://{host}:{port} (auth: {'token' if token else 'INSECURE'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
        log_event(_log, logging.INFO, "service.stop", host=host, port=port)
    return 0


def cmd_token(args) -> int:
    print(generate_token())
    return 0


def cmd_init(args) -> int:
    service = ControlService(args.db)
    service.close()
    print(f"initialized database at {args.db}")
    return 0


def cmd_test(args) -> int:
    import io
    import pathlib
    import unittest

    here = pathlib.Path(__file__).resolve().parent.parent
    loader = unittest.TestLoader()
    suite = loader.discover(str(here / "tests"), top_level_dir=str(here))
    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    result = runner.run(suite)
    sys.stdout.write(buf.getvalue())
    return 0 if result.wasSuccessful() else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os", description="Agent OS / Mission Control")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the local control API + UI")
    p_serve.add_argument("--db", required=True, help="path to the SQLite database")
    p_serve.add_argument("--host", default=DEFAULT_HOST, help="bind host (default 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind port (default 8470)")
    p_serve.add_argument("--token", help="bearer token (else AGENT_OS_TOKEN)")
    p_serve.add_argument("--insecure", action="store_true", help="serve without auth (dev/test only)")
    p_serve.add_argument(
        "--fake-behavior", default="success",
        choices=["success", "missing_evidence", "crash_after_effect"],
        help="behavior of the fake executor (default success)",
    )
    p_serve.add_argument(
        "--enable-subprocess", action="store_true",
        help="EXPLICIT GATE: register the real subprocess executor",
    )
    p_serve.add_argument(
        "--source-workspace", default=None,
        help="source dir the subprocess executor copies to a disposable sandbox",
    )
    p_serve.add_argument(
        "--sandbox-root", default=None,
        help="where disposable sandboxes are created (default: <db dir>/sandboxes)",
    )
    p_serve.add_argument(
        "--subprocess-timeout", type=int, default=120,
        help="hard timeout per subprocess run in seconds (default 120)",
    )
    p_serve.add_argument(
        "--keep-sandbox", action="store_true",
        help="keep disposable sandboxes after runs for inspection",
    )

    sub.add_parser("token", help="print a fresh random bearer token")
    p_init = sub.add_parser("init", help="initialize a database")
    p_init.add_argument("--db", required=True)
    sub.add_parser("test", help="run the enforcement test suite")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {
        "serve": cmd_serve,
        "token": cmd_token,
        "init": cmd_init,
        "test": cmd_test,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
