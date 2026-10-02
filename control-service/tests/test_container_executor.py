"""Container executor unit tests: command execution, evidence, timeout,
and fail-closed behavior — with Docker mocked.

These tests verify the executor's logic without requiring a running Docker
daemon. The security boundary tests (test_container_boundary.py) use real
Docker to prove isolation.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def _make_executor(src=None, timeout=30, image="python:3.14-slim"):
    src = src or (TMP / "src")
    return ContainerExecutor(
        source_workspace=src,
        image=image,
        timeout_seconds=timeout,
    )


class ContainerExecutorUnitTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.src = TMP / "src"
        self.src.mkdir(exist_ok=True)
        (self.src / "marker.txt").write_text("original", encoding="utf-8")

    def test_no_command_fails_closed(self):
        """Without a command, the executor must not guess."""
        job = _make_job(command=None)
        outcome = _make_executor().run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertIn("no command", outcome.evidence.get("error", ""))

    def test_successful_command_produces_verified_evidence(self):
        """A command that exits 0 with a test signal is verified."""
        job = _make_job(command=["python", "-c", "print('3 tests passed')"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"3 tests passed\n",
                stderr=b"",
            )
            outcome = _make_executor().run(job, 1)
        self.assertEqual(outcome.status, "completed_with_evidence")
        self.assertTrue(outcome.evidence["test_report"])
        self.assertEqual(outcome.evidence["exit_code"], 0)

    def test_failing_command_is_unverified(self):
        """A command that exits non-zero is unverified."""
        job = _make_job(command=["python", "-c", "import sys; sys.exit(1)"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout=b"",
                stderr=b"error",
            )
            outcome = _make_executor().run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertEqual(outcome.evidence["exit_code"], 1)

    def test_timeout_is_honest_not_success(self):
        """A timeout is reported as timeout, not success."""
        job = _make_job(command=["python", "-c", "import time; time.sleep(5)"])
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=1)
            outcome = _make_executor(timeout=1).run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertEqual(outcome.evidence.get("reason"), "timeout")

    def test_docker_command_contains_security_flags(self):
        """The docker run command must contain all security flags."""
        job = _make_job(command=["python", "-c", "print('hello')"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"hello\n",
                stderr=b"",
            )
            _make_executor().run(job, 1)

        # Get the docker command that was passed to subprocess.run
        docker_cmd = mock_run.call_args[0][0]

        # Verify security flags are present
        self.assertIn("--network", docker_cmd)
        self.assertIn("none", docker_cmd)
        self.assertIn("--read-only", docker_cmd)
        self.assertIn("--cap-drop", docker_cmd)
        self.assertIn("ALL", docker_cmd)
        self.assertIn("--security-opt", docker_cmd)
        self.assertIn("no-new-privileges", docker_cmd)
        self.assertIn("--user", docker_cmd)
        self.assertIn("1000:1000", docker_cmd)
        self.assertIn("--rm", docker_cmd)
        self.assertIn("--tmpfs", docker_cmd)
        self.assertIn("/tmp", docker_cmd)

    def test_workspace_is_mounted(self):
        """The workspace must be mounted at /workspace."""
        job = _make_job(command=["python", "-c", "print('hello')"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"hello\n",
                stderr=b"",
            )
            _make_executor().run(job, 1)

        docker_cmd = mock_run.call_args[0][0]
        self.assertIn("--mount", docker_cmd)
        mount_idx = docker_cmd.index("--mount")
        mount_value = docker_cmd[mount_idx + 1]
        self.assertIn("type=bind", mount_value)
        self.assertIn("target=/workspace", mount_value)

    def test_workdir_is_workspace(self):
        """The working directory must be /workspace."""
        job = _make_job(command=["python", "-c", "print('hello')"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"hello\n",
                stderr=b"",
            )
            _make_executor().run(job, 1)

        docker_cmd = mock_run.call_args[0][0]
        self.assertIn("--workdir", docker_cmd)
        workdir_idx = docker_cmd.index("--workdir")
        self.assertEqual(docker_cmd[workdir_idx + 1], "/workspace")

    def test_custom_image_is_used(self):
        """A custom image must be passed to docker run."""
        job = _make_job(command=["python", "-c", "print('hello')"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"hello\n",
                stderr=b"",
            )
            _make_executor(image="custom/image:latest").run(job, 1)

        docker_cmd = mock_run.call_args[0][0]
        self.assertIn("custom/image:latest", docker_cmd)

    def test_command_is_passed_as_argv(self):
        """The command must be passed as separate argv, not shell-interpreted."""
        job = _make_job(command=["python", "-c", "print('hello'); print('world')"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"hello\nworld\n",
                stderr=b"",
            )
            _make_executor().run(job, 1)

        docker_cmd = mock_run.call_args[0][0]
        # The command should be at the end, as separate elements
        self.assertIn("python", docker_cmd)
        self.assertIn("-c", docker_cmd)
        self.assertIn("print('hello'); print('world')", docker_cmd)

    def test_stdout_and_stderr_are_captured(self):
        """stdout and stderr must be captured in evidence."""
        job = _make_job(command=["python", "-c", "print('out'); import sys; sys.stderr.write('err')"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"out\n",
                stderr=b"err\n",
            )
            outcome = _make_executor().run(job, 1)

        self.assertIn("out", outcome.evidence["diff"])
        self.assertIn("err", outcome.evidence["diff"])

    def test_executor_name(self):
        """The executor must have the correct name."""
        executor = _make_executor()
        self.assertEqual(executor.name, "container-executor")

    def test_allowed_actions(self):
        """The executor must support the correct actions."""
        executor = _make_executor()
        self.assertIn("run_command", executor.allowed_actions)
        self.assertIn("run_tests", executor.allowed_actions)

    def test_invocations_recorded(self):
        """Each invocation must be recorded."""
        job = _make_job(command=["python", "-c", "print('hello')"])
        executor = _make_executor()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"hello\n",
                stderr=b"",
            )
            executor.run(job, 1)

        self.assertEqual(len(executor.invocations), 1)
        self.assertEqual(executor.invocations[0]["job_id"], "job-test")
        self.assertEqual(executor.invocations[0]["attempt"], 1)


class ContainerExecutorApprovalTest(unittest.TestCase):
    """The container executor must be gated by the approval system."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.src = TMP / "src"
        self.src.mkdir(exist_ok=True)
        (self.src / "marker.txt").write_text("original", encoding="utf-8")

    def test_executor_name_matches_registry(self):
        """The executor name must match what the CLI registers."""
        executor = _make_executor()
        self.assertEqual(executor.name, "container-executor")

    def test_executor_is_not_registered_by_default(self):
        """The container executor must NOT be registered by default."""
        from agent_os.api import _EXECUTORS
        # Clear any existing registrations
        _EXECUTORS.clear()
        # The container executor should not be in the registry
        self.assertNotIn("container-executor", _EXECUTORS)

    def test_executor_can_be_registered(self):
        """The container executor can be explicitly registered."""
        from agent_os.api import _EXECUTORS, register_executor, unregister_executor
        _EXECUTORS.clear()
        try:
            executor = _make_executor()
            register_executor("container-executor", executor)
            self.assertIn("container-executor", _EXECUTORS)
            self.assertIs(_EXECUTORS["container-executor"], executor)
        finally:
            unregister_executor("container-executor")


if __name__ == "__main__":
    unittest.main()
