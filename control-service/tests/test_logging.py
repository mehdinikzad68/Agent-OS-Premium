"""Tests for the structured logging subsystem.

The contract these tests lock down:
- a log line is a self-describing JSON object with mandatory keys,
- secrets are masked BEFORE any handler writes, including inside a
  traceback and including a live secret registered at runtime,
- logging is inert unless it is configured, so tests and library use stay quiet.

Standard library only.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from agent_os import logging_setup  # noqa: E402
from agent_os.logging_setup import (  # noqa: E402
    RedactingFilter,
    configure,
    get_logger,
    log_event,
    redact,
    register_secret,
)

REQUIRED_KEYS = {"ts", "level", "logger", "event", "message"}


class LoggingTestCase(unittest.TestCase):
    def setUp(self):
        pkg = logging.getLogger(logging_setup.PACKAGE_LOGGER)
        self._saved_handlers = list(pkg.handlers)
        self._saved_level = pkg.level
        self._saved_propagate = pkg.propagate
        self._saved_filters = list(pkg.filters)
        self._saved_secrets = set(logging_setup._LIVE_SECRETS)
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._restore)

    def _restore(self):
        pkg = logging.getLogger(logging_setup.PACKAGE_LOGGER)
        for handler in list(pkg.handlers):
            pkg.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass
        for handler in self._saved_handlers:
            pkg.addHandler(handler)
        pkg.filters = self._saved_filters
        pkg.setLevel(self._saved_level)
        pkg.propagate = self._saved_propagate
        logging_setup._LIVE_SECRETS.clear()
        logging_setup._LIVE_SECRETS.update(self._saved_secrets)

    def read_lines(self) -> list[dict]:
        files = sorted(self.log_dir.glob("agent-os-*.jsonl*"))
        records = []
        for path in files:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records


class JsonLineShapeTest(LoggingTestCase):
    def test_record_has_mandatory_keys(self):
        configure(log_dir=self.log_dir, console=False)
        log_event(get_logger("test"), logging.INFO, "unit.ping", answer=42)
        records = self.read_lines()
        self.assertEqual(len(records), 1, f"expected one line, got {records}")
        missing = REQUIRED_KEYS - set(records[0])
        self.assertFalse(missing, f"mandatory keys missing: {missing}")

    def test_structured_fields_are_top_level(self):
        configure(log_dir=self.log_dir, console=False)
        log_event(
            get_logger("test"),
            logging.INFO,
            "job.dispatched",
            job_id="job-1",
            attempt=3,
        )
        rec = self.read_lines()[0]
        self.assertEqual(rec["event"], "job.dispatched")
        self.assertEqual(rec["job_id"], "job-1")
        self.assertEqual(rec["attempt"], 3)

    def test_exception_is_attached_to_the_record(self):
        configure(log_dir=self.log_dir, console=False)
        try:
            raise RuntimeError("boom while verifying evidence")
        except RuntimeError:
            log_event(get_logger("test"), logging.ERROR, "job.failed", exc_info=True)
        rec = self.read_lines()[0]
        self.assertIn("exc", rec, "traceback missing from the record")
        self.assertIn("RuntimeError", rec["exc"])


class RedactionTest(LoggingTestCase):
    def test_github_token_shape_is_masked(self):
        text = "pushing with ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 now"
        self.assertNotIn("ghp_ABCDEF", redact(text))
        self.assertIn("[REDACTED]", redact(text))

    def test_provider_and_aws_key_shapes_are_masked(self):
        for secret in (
            "sk-abcdefghijklmnopqrstuvwxyz012345",
            "AKIAIOSFODNN7EXAMPLE",
            "github_pat_11ABCDEFG0abcdefghijklmnop",
        ):
            with self.subTest(secret=secret[:8]):
                out = redact(f"value={secret}")
                self.assertNotIn(secret, out)
                self.assertIn("[REDACTED]", out)

    def test_authorization_header_is_masked(self):
        out = redact("Authorization: Bearer abcdef1234567890XYZ")
        self.assertNotIn("abcdef1234567890XYZ", out)
        self.assertNotIn("Bearer", out, "the whole header value is masked, scheme included")
        self.assertIn("Authorization", out, "the field name must survive so the log stays readable")

    def test_bare_bearer_token_is_masked(self):
        out = redact("sent bearer abcdef1234567890XYZ upstream")
        self.assertNotIn("abcdef1234567890XYZ", out)
        self.assertIn("bearer", out)

    def test_credential_key_value_is_masked(self):
        out = redact('{"api_key": "s3cr3t-value-here", "mission": "demo"}')
        self.assertNotIn("s3cr3t-value-here", out)
        self.assertIn("demo", out, "unrelated field must survive redaction")

    def test_redaction_never_duplicates_surrounding_text(self):
        # Regression: the masking helper once returned the text BEFORE the
        # match as well, and re.sub kept that text too, so the prefix came out
        # twice ("sent sent bearer [REDACTED] upstream"). Every surrounding
        # word must appear exactly once after redaction.
        cases = [
            ("sent bearer abcdef1234567890XYZ upstream", "sent", "upstream"),
            ("before ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 after", "before", "after"),
            ('lead {"api_key": "s3cr3t-value-here"} tail', "lead", "tail"),
        ]
        for text, prefix, suffix in cases:
            with self.subTest(prefix=prefix):
                out = redact(text)
                self.assertEqual(out.count(prefix), 1, f"prefix {prefix!r} duplicated in {out!r}")
                self.assertEqual(out.count(suffix), 1, f"suffix {suffix!r} duplicated in {out!r}")

    def test_redaction_preserves_length_relationship(self):
        # A masked line must not grow by more than the placeholder expansion.
        text = "connect with ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 now"
        out = redact(text)
        self.assertLessEqual(
            len(out),
            len(text) - 36 + len("[REDACTED]") + 1,
            f"output unexpectedly long: {out!r}",
        )
        self.assertTrue(out.startswith("connect with "))
        self.assertTrue(out.endswith(" now"))

    def test_registered_live_secret_is_masked(self):
        register_secret("live-token-abc123DEF456")
        out = redact("connecting with live-token-abc123DEF456")
        self.assertNotIn("live-token-abc123DEF456", out)

    def test_short_values_are_not_registered(self):
        register_secret("abc")
        self.assertNotIn("abc", logging_setup._LIVE_SECRETS)

    def test_secret_in_traceback_never_reaches_the_file(self):
        register_secret("live-token-abc123DEF456")
        configure(log_dir=self.log_dir, console=False)
        try:
            raise RuntimeError("auth failed for live-token-abc123DEF456")
        except RuntimeError:
            log_event(get_logger("test"), logging.ERROR, "auth.failed", exc_info=True)
        raw = "".join(
            p.read_text(encoding="utf-8", errors="replace")
            for p in self.log_dir.glob("agent-os-*.jsonl*")
        )
        self.assertNotIn("live-token-abc123DEF456", raw)

    def test_filter_rewrites_the_record_in_place(self):
        rec = logging.LogRecord("agent_os.t", logging.INFO, __file__, 1, "using ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", None, None)
        RedactingFilter().filter(rec)
        self.assertNotIn("ghp_ABCDEF", rec.getMessage())


class ConfigurationTest(LoggingTestCase):
    def test_disabled_logging_writes_nothing(self):
        result = configure(log_dir=self.log_dir, enabled=False)
        log_event(get_logger("test"), logging.ERROR, "should.not.appear")
        self.assertIsNone(result)
        self.assertEqual(self.read_lines(), [])

    def test_configure_is_idempotent_and_does_not_duplicate_handlers(self):
        configure(log_dir=self.log_dir, console=False)
        configure(log_dir=self.log_dir, console=False)
        pkg = logging.getLogger(logging_setup.PACKAGE_LOGGER)
        file_handlers = [
            h for h in pkg.handlers if isinstance(h, logging.FileHandler)
        ]
        self.assertEqual(len(file_handlers), 1, "handlers accumulated across configure()")
        log_event(get_logger("test"), logging.INFO, "unit.once")
        self.assertEqual(len(self.read_lines()), 1)

    def test_unwritable_log_dir_degrades_quietly(self):
        # A file where a directory is expected: configure must not raise.
        blocker = self.log_dir / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        result = configure(log_dir=blocker / "nested", console=False)
        self.assertIsNone(result)

    def test_default_log_dir_honours_env_override(self):
        old = os.environ.get("AGENT_OS_LOG_DIR")
        os.environ["AGENT_OS_LOG_DIR"] = str(self.log_dir)
        try:
            self.assertEqual(logging_setup.default_log_dir(), self.log_dir)
        finally:
            if old is None:
                os.environ.pop("AGENT_OS_LOG_DIR", None)
            else:
                os.environ["AGENT_OS_LOG_DIR"] = old

    def test_debug_env_raises_level_to_debug(self):
        old = os.environ.get("AGENT_OS_DEBUG")
        os.environ["AGENT_OS_DEBUG"] = "1"
        try:
            self.assertTrue(logging_setup.is_debug())
        finally:
            if old is None:
                os.environ.pop("AGENT_OS_DEBUG", None)
            else:
                os.environ["AGENT_OS_DEBUG"] = old


class RequestLogTest(LoggingTestCase):
    """The request trail, against a real HTTP server.

    The unit tests could not catch two defects that only appear once real
    requests go through a socket: the status came out as None on every line
    (http.server keeps the code in a local, not on self), and the UI shell
    request was never recorded at all because it bypasses the router.
    """

    def _serve_and_hit(self, paths):
        import threading
        import time
        import urllib.error
        import urllib.request

        from agent_os.api import serve
        from agent_os.service import ControlService

        db = self.log_dir / "reqlog.db"
        service = ControlService(db)
        import socket as _socket
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
            _s.bind(("127.0.0.1", 0))  # kernel-chosen (B3): no fixed port
            port = _s.getsockname()[1]
        server = serve(service, host="127.0.0.1", port=port, token="t" * 20, insecure=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        time.sleep(0.3)
        codes = []
        try:
            for path, headers in paths:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}", headers=headers
                )
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        codes.append((path, resp.status))
                except urllib.error.HTTPError as exc:
                    codes.append((path, exc.code))
        finally:
            server.shutdown()
            server.server_close()
            service.close()
        return codes

    def test_every_request_is_recorded_with_a_real_status(self):
        configure(log_dir=self.log_dir, level=logging.DEBUG, console=False)
        auth = {"Authorization": "Bearer " + "t" * 20}
        codes = self._serve_and_hit(
            [("/api/status", auth), ("/api/status", {}), ("/", {})]
        )
        self.assertEqual([c for _, c in codes], [200, 401, 200])

        requests = [r for r in self.read_lines() if r.get("event") == "http.request"]
        self.assertEqual(len(requests), 3, f"one line per request expected, got {requests}")
        for record in requests:
            self.assertIsNotNone(
                record.get("status"),
                f"status must be recorded, not None: {record!r}",
            )
            self.assertIsInstance(record.get("duration_ms"), (int, float))
        self.assertEqual([r["status"] for r in requests], [200, 401, 200])

    def test_request_is_recorded_exactly_once(self):
        configure(log_dir=self.log_dir, level=logging.DEBUG, console=False)
        auth = {"Authorization": "Bearer " + "t" * 20}
        self._serve_and_hit([("/api/status", auth)])
        events = [r.get("event") for r in self.read_lines()]
        self.assertEqual(events.count("http.request"), 1, f"duplicate records: {events}")
        self.assertNotIn(
            "http.access", events, "the framework access line must not duplicate http.request"
        )


if __name__ == "__main__":
    unittest.main()
