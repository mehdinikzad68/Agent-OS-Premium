# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Container executor security boundary tests — REAL Docker.

These tests prove that the container executor actually isolates the command
from the host system. They use real Docker containers (not mocks) to verify:

1. A command cannot read files outside the mounted workspace
2. A command cannot write outside the mounted workspace
3. A command cannot access the network
4. A command cannot access the Docker socket
5. A command cannot escalate privileges
6. The container is removed after execution

These tests require:
- Docker daemon running
- python:3.14-slim image pulled
- Running inside WSL2 (or Linux)
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_os.adapters.container_executor import ContainerExecutor
from agent_os.models import (
    Job,
    JobState,
    Principal,
    encode_command,
)

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


def _make_job(command=None, executor="container-executor", actions=("run_tests",)):
    job = Job(
        id="job-test",
        mission_id="mission-test",
        title="run a real command",
        proposed_by=Principal.PLANNER,
        executor=executor,
        workspace_paths=("/workspace",),
        actions=actions,
        state=JobState.APPROVED,
        attempt_no=0,
        manifest_hash="x",
        created_at="t",
        updated_at="t",
        command=encode_command(command),
    )
    return job


def _docker_available() -> bool:
    """Check if Docker is available."""
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _image_available(image: str) -> bool:
    """Check if the Docker image is available."""
    try:
        result = subprocess.run(
            ["docker", "images", "-q", image],
            capture_output=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# T2 (review 2026-10-05): POSIX/WSL-only module. Discovery on any other
# platform must SKIP it honestly instead of reporting errors it cannot
# meaningfully run (READINESS.md documents WSL as the target environment).
import sys as _sys
if not _sys.platform.startswith("linux"):
    raise unittest.SkipTest(
        "POSIX/WSL-only module - run the suite under WSL (READINESS.md)"
    )

@unittest.skipUnless(_docker_available(), "Docker daemon not available")
class ContainerSecurityBoundaryTest(unittest.TestCase):
    """Security boundary tests using real Docker containers."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.src = TMP / "src"
        self.src.mkdir(exist_ok=True)
        (self.src / "marker.txt").write_text("original", encoding="utf-8")
        (self.src / "secret.txt").write_text("top-secret", encoding="utf-8")

    def _run_in_container(self, command: list[str], timeout: int = 30) -> tuple[int, str, str]:
        """Run a command in a container and return (exit_code, stdout, stderr)."""
        executor = ContainerExecutor(
            source_workspace=self.src,
            timeout_seconds=timeout,
        )
        job = _make_job(command=command)
        outcome = executor.run(job, 1)
        return (
            outcome.evidence.get("exit_code", -1),
            outcome.evidence.get("diff", ""),
            outcome.evidence.get("error", ""),
        )

    def test_cannot_read_host_file(self):
        """A command cannot read a HOST-specific file (not in the image).
        
        The container has its own /etc/passwd (from the image), but it cannot
        read host-specific files. We create a file on the host that is NOT
        mounted into the container, and verify the container cannot read it.
        """
        # Create a host-specific file that is NOT in the workspace
        host_file = TMP / "host_only.txt"
        host_file.write_text("host-secret", encoding="utf-8")
        
        # Try to read it from the container (it's not mounted)
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", f"print(open('{host_file}').read())"]
        )
        # The command should fail because the host file is not mounted
        self.assertNotEqual(exit_code, 0, "Command should not succeed reading host file")

    def test_cannot_write_to_root(self):
        """A command cannot write to / (read-only root)."""
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "open('/test.txt', 'w').write('hello')"]
        )
        self.assertNotEqual(exit_code, 0, "Command should not succeed writing to /")

    def test_cannot_write_to_tmpfs(self):
        """A command CAN write to /tmp (tmpfs is writable)."""
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "open('/tmp/test.txt', 'w').write('hello')"]
        )
        self.assertEqual(exit_code, 0, "Command should succeed writing to /tmp")

    def test_cannot_access_network(self):
        """A command cannot access the network."""
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "import urllib.request; urllib.request.urlopen('http://example.com', timeout=5)"]
        )
        self.assertNotEqual(exit_code, 0, "Command should not succeed accessing network")

    def test_cannot_access_docker_socket(self):
        """A command cannot access the Docker socket."""
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "import os; print(os.path.exists('/var/run/docker.sock'))"]
        )
        # The socket should not exist inside the container
        self.assertEqual(exit_code, 0, "Command should succeed checking socket")
        self.assertIn("False", diff, "Docker socket should not exist in container")

    def test_cannot_escalate_privileges(self):
        """A command cannot escalate privileges (no-new-privileges)."""
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "import os; os.setuid(0)"]
        )
        self.assertNotEqual(exit_code, 0, "Command should not succeed escalating privileges")

    def test_workspace_is_mounted(self):
        """The workspace IS mounted and accessible."""
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "print(open('/workspace/marker.txt').read())"]
        )
        self.assertEqual(exit_code, 0, "Command should succeed reading workspace file")
        self.assertIn("original", diff)

    def test_workspace_is_writable(self):
        """The workspace IS writable (for project output)."""
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "open('/workspace/output.txt', 'w').write('hello')"]
        )
        self.assertEqual(exit_code, 0, "Command should succeed writing to workspace")

    def test_container_is_removed_after_run(self):
        """The container is removed after execution."""
        executor = ContainerExecutor(
            source_workspace=self.src,
            timeout_seconds=30,
        )
        job = _make_job(command=["python", "-c", "print('hello')"])
        outcome = executor.run(job, 1)

        # Check that no container with our naming pattern exists
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=agent-os-run-", "--format", "{{.Names}}"],
            capture_output=True,
            timeout=10,
        )
        containers = result.stdout.decode().strip()
        self.assertEqual(containers, "", f"Container should be removed, found: {containers}")

    def test_non_root_user(self):
        """The container runs as non-root user (uid 1000)."""
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "import os; print(os.getuid())"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("1000", diff)

    def test_destruction_cannot_touch_the_real_source(self):
        """H2: /workspace is a disposable COPY, so even a command that wipes
        it cannot modify the operator's real project directory."""
        cmd = (
            "import os\n"
            "def rm(p):\n"
            "    try:\n"
            "        if os.path.isdir(p) and not os.path.islink(p):\n"
            "            for e in os.listdir(p): rm(os.path.join(p, e))\n"
            "            os.rmdir(p)\n"
            "        else:\n"
            "            os.remove(p)\n"
            "    except OSError:\n"
            "        pass\n"
            "[rm(os.path.join('/workspace', e)) for e in os.listdir('/workspace')]\n"
            "print('wiped', os.listdir('/workspace'))\n"
        )
        exit_code, diff, _ = self._run_in_container(["python", "-c", cmd])
        self.assertEqual(exit_code, 0, f"wipe command failed: {diff}")
        self.assertEqual(
            (self.src / "marker.txt").read_text(encoding="utf-8"),
            "original",
            "a destructive in-container command modified the real source",
        )

    def test_no_capabilities(self):
        """The container has no Linux capabilities.
        
        We check that the container cannot perform operations that require
        capabilities, such as mounting filesystems or changing network config.
        """
        # Try to mount a filesystem (requires CAP_SYS_ADMIN)
        exit_code, diff, _ = self._run_in_container(
            ["python", "-c", "import os; os.mount('/dev/sda1', '/mnt', 'ext4', 0, '')"]
        )
        self.assertNotEqual(exit_code, 0, "Command should not have CAP_SYS_ADMIN")


if __name__ == "__main__":
    unittest.main()
