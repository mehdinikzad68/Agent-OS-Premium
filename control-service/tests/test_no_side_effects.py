# -*- coding: utf-8 -*-
"""Make the no-execute / no-network proof permanent.

The roadmap's Phase 2 exit criterion is one line: registering a project must
not cause a mount or a command execution. That was satisfied by accident as
easily as by design, and reading the code is not evidence - the test has to
run the real path and watch the machine.

sys.addaudithook is the right instrument here and not just because strace is
missing. The project declares `dependencies = []`, so there is no third-party
library that could reach the OS without passing through CPython's audit hook.
The silence is therefore a strong claim rather than a lucky one.

Two design points worth keeping if this is ever extended:

  The hook is addedaudithook, not a logger filter. It cannot be removed once
  installed, and it fires for every audit event in the process, so it sees
  the service's own code AND anything it calls into.

  It arms a control. After the assertions, the test makes one real
  subprocess.run and requires the hook to have caught it. Without that, a hook
  that was never installed would produce a passing test - the silence would
  mean nothing. This is the part that makes the negative result trustworthy.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Measured on this interpreter: subprocess.run emits subprocess.POpen and
# os.posix_spawn; os.system emits os.system; ctypes.CDLL emits ctypes.dlopen.
# There is no subprocess.run audit event - do not guard for one, it can never
# fire and its absence proves nothing.
EXEC_FAMILY = (
    "subprocess.Popen", "os.posix_spawn", "os.system", "os.exec", "os.fork",
    "os.forkpty", "os.startfile", "pty.spawn", "ctypes.dlopen", "ctypes.dlsym",
    "ctypes.call_function",
)
NETWORK = ("socket.connect", "urllib.Request")

# installed once, for the whole process; the lists are module state on purpose
HITS: list = []
_OUTBOUND: list = []


def _hook(event, args):
    if event in EXEC_FAMILY:
        HITS.append((event, repr(args)[:120]))
    if event in NETWORK:
        _OUTBOUND.append((event, repr(args)[:120]))


if not any(getattr(h, "_agent_os_audit", False) for h in []):  # pragma: no cover
    sys.addaudithook(_hook)
    _hook._agent_os_audit = True  # type: ignore[attr-defined]

from agent_os.service import ControlService, ProjectRejected  # noqa: E402

REAL = "/home/mehdi/workspace/wp-bioscentiran"


class NoSideEffectTest(unittest.TestCase):
    """Registration and removal must not execute or reach the network."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svc = ControlService(Path(self.tmp.name) / "n.db")
        self.addCleanup(self.svc.close)
        os.environ["AGENT_OS_PROJECT_SCOPE"] = "/home/mehdi/workspace"
        self.addCleanup(os.environ.pop, "AGENT_OS_PROJECT_SCOPE", None)

    def test_the_audit_hook_is_actually_armed(self):
        """The control. Run this file's own test with the hook removed and it
        still passes - which is exactly why the control exists."""
        HITS.clear()
        subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
        self.assertTrue(
            [e for e, _ in HITS],
            "the audit hook is not installed, so every negative result in this "
            "file is worthless")
        # it must be the real event, not just any event
        self.assertTrue(
            [e for e, _ in HITS if e in EXEC_FAMILY],
            f"the hook fired but not on an execution event: {HITS}")

    def test_registering_executes_nothing(self):
        HITS.clear()
        _OUTBOUND.clear()
        p = self.svc.register_project(name="s", environment="wsl", root=REAL)
        self.assertEqual(HITS, [], f"registration executed: {HITS}")
        self.assertEqual(_OUTBOUND, [], f"registration networked: {_OUTBOUND}")
        self.svc.remove_project(p.id)

    def test_every_refusal_path_executes_nothing(self):
        HITS.clear()
        escape = Path(self.tmp.name) / "escape"
        escape.symlink_to("/etc")
        # /home/mehdi/workspace is NOT here: it is a real directory inside the
        # scope and registering it is supposed to succeed.
        absent = "/home/mehdi/workspace/no-such-project-9f2c"
        for root in ("/etc", "relative/path", str(escape), absent):
            with self.assertRaises(ProjectRejected) as ctx:
                self.svc.register_project(name="x", environment="wsl", root=root)
            print_reason = getattr(ctx.exception, "reason", None)
            if print_reason is None:
                self.fail("ProjectRejected carried no structured reason")
        with self.assertRaises(ProjectRejected):
            self.svc.register_project(name="x", environment="windows", root=REAL)
        self.assertEqual(HITS, [], f"a refusal path executed: {HITS}")

    def test_removal_executes_nothing(self):
        p = self.svc.register_project(name="s", environment="wsl", root=REAL)
        HITS.clear()
        self.assertTrue(self.svc.remove_project(p.id))
        self.assertEqual(HITS, [], f"removal executed: {HITS}")

    def test_duplicate_refusal_executes_nothing(self):
        self.svc.register_project(name="s", environment="wsl", root=REAL)
        HITS.clear()
        with self.assertRaises(ProjectRejected) as ctx:
            self.svc.register_project(name="other", environment="wsl", root=REAL)
        self.assertEqual(ctx.exception.reason, "duplicate")
        self.assertEqual(HITS, [], f"the duplicate path executed: {HITS}")

    def test_the_codebase_declares_no_third_party_dependency(self):
        """The audit hook's strength rests on this. If a dependency ever lands
        that shells out through a C extension, the hook may not see it, and
        these tests would be quietly worth less."""
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml")
        text = pyproject.read_text(encoding="utf-8")
        self.assertIn("dependencies = []", text,
                      "pyproject.toml no longer declares dependencies = []; the "
                      "audit-hook proof above needs re-examining")


if __name__ == "__main__":
    unittest.main()
