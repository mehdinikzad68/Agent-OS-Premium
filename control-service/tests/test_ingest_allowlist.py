"""M1 (B2): ingest sources are allowlisted.

Before the fix, POST /api/events/ingest read ANY local SQLite path the
caller supplied (a token-gated arbitrary-read primitive). Allowed roots:
$AGENT_OS_INGEST_ROOTS plus the Hermes profile locations that
default_profile_db() could name. Resolution decides, so `..` and a
symlink planted inside an allowed root cannot widen the boundary."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_os.service import ControlService

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class IngestAllowlistTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix="ing-allow-", dir=str(TMP))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._prev = os.environ.get("AGENT_OS_INGEST_ROOTS")
        os.environ["AGENT_OS_INGEST_ROOTS"] = self.tmp

        def _restore_roots():
            if self._prev is None:
                os.environ.pop("AGENT_OS_INGEST_ROOTS", None)
            else:
                os.environ["AGENT_OS_INGEST_ROOTS"] = self._prev

        self.addCleanup(_restore_roots)
        self.svc = ControlService(Path(self.tmp) / "svc.db")
        self.addCleanup(self.svc.close)

    def test_source_inside_allowed_root_passes_the_gate(self):
        src = Path(self.tmp) / "state.db"
        src.write_bytes(b"")
        try:
            out = self.svc.ingest_external(str(src))
        except PermissionError:
            self.fail("source inside the allowed root was refused")
        except Exception:
            return  # past the gate: an empty file is not Hermes-shaped
        self.assertIn(out["status"], ("ok", "unavailable"))

    def test_source_outside_allowed_roots_is_refused(self):
        with self.assertRaises(PermissionError):
            self.svc.ingest_external("/etc/passwd")

    def test_symlink_inside_the_root_cannot_reach_outside(self):
        link = Path(self.tmp) / "trap.db"
        os.symlink("/etc/passwd", link)
        with self.assertRaises(PermissionError):
            self.svc.ingest_external(str(link))

    def test_hermes_default_root_is_allowed_without_env(self):
        """No env set -> the built-in Hermes locations still work (p4/UI)."""
        os.environ.pop("AGENT_OS_INGEST_ROOTS", None)
        fake_home = Path(tempfile.mkdtemp(prefix="ing-home-", dir=str(TMP)))
        self.addCleanup(shutil.rmtree, fake_home, True)
        prev_home = os.environ.get("HOME")
        os.environ["HOME"] = str(fake_home)

        def _restore_home():
            if prev_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = prev_home

        self.addCleanup(_restore_home)
        src = fake_home / ".hermes" / "profiles" / "p" / "state.db"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"")
        try:
            self.svc.ingest_external(str(src))
        except PermissionError:
            self.fail("the built-in Hermes default root was refused")
        except Exception:
            return  # past the gate


if __name__ == "__main__":
    unittest.main(verbosity=2)
