""" Hermes executor unit tests: command validation, binary resolution,
evidence collection, and fail-closed behavior — with subprocess mocked.

These tests verify the executor's logic without requiring a running Hermes
installation. The executor's interaction with the Hermes CLI is mocked.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_os.adapters.hermes_executor import HermesExecutor, _find_hermes
from agent_os.models import (
    Job,
    JobState,
    Principal,
    encode_command,
)

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


def _make_job(command=None, executor="hermes-executor", actions=("delegate_task",)):
    job = Job(
        id="job-test",
        mission_id="mission-test",
        title="delegate to hermes",
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


def _make_executor(src=None, timeout=30, hermes_binary="/fake/hermes"):
    src = src or (TMP / "src")
    return HermesExecutor(
        source_workspace=src,
        timeout_seconds=timeout,
        hermes_binary=hermes_binary,
    )


class HermesExecutorUnitTest(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.src = TMP / "src"
        self.src.mkdir(exist_ok=True)
        (self.src / "marker.txt").write_text("original", encoding="utf-8")

    def tearDown(self):
        # Remove any stale usage files left in src by interrupted runs or
        # tests that pre-create them (pre-fix behavior). This is the only
        # cleanup needed; the src dir itself must persist across tests in
        # this class because setUp is not the right place to blow it away.
        for f in self.src.glob(".agent-os-usage-*.json"):
            f.unlink(missing_ok=True)

    def test_no_command_fails_closed(self):
        """Without a command, the executor must not guess."""
        job = _make_job(command=None)
        outcome = _make_executor().run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertIn("no command", outcome.evidence.get("error", ""))

    def test_single_element_command_fails_closed(self):
        """A command with only an operator (no prompt) must fail."""
        job = _make_job(command=["solve"])
        outcome = _make_executor().run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertIn("at least 2 elements", outcome.evidence.get("error", ""))

    def test_no_hermes_binary_fails_closed(self):
        """If hermes binary is not found, fail closed."""
        job = _make_job(command=["solve", "fix the bug"])
        executor = HermesExecutor(
            source_workspace=self.src,
            hermes_binary=None,
        )
        # Mock _find_hermes to return None
        with patch("agent_os.adapters.hermes_executor._find_hermes", return_value=None):
            executor.hermes_binary = None
            outcome = executor.run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertIn("hermes binary not found", outcome.evidence.get("error", ""))

    def test_successful_delegation_produces_verified_evidence(self):
        """A successful hermes run (exit 0 with output) is verified."""
        job = _make_job(command=["solve", "fix the failing test"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"Fixed the test. All 3 tests pass now.\n",
                stderr=b"",
            )
            outcome = _make_executor().run(job, 1)
        self.assertEqual(outcome.status, "completed_with_evidence")
        self.assertTrue(outcome.evidence["test_report"])
        self.assertEqual(outcome.evidence["exit_code"], 0)
        self.assertIn("Fixed the test", outcome.evidence["hermes_response"])

    def test_failing_delegation_is_unverified(self):
        """A hermes run with non-zero exit is unverified."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout=b"",
                stderr=b"error: model not found",
            )
            outcome = _make_executor().run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertEqual(outcome.evidence["exit_code"], 1)

    def test_timeout_is_honest_not_success(self):
        """A timeout is reported as timeout, not success."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="hermes", timeout=1)
            outcome = _make_executor(timeout=1).run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertEqual(outcome.evidence.get("reason"), "timeout")

    def test_usage_file_is_read(self):
        """If hermes produces a usage file, it is included in evidence."""
        import tempfile
        job = _make_job(command=["solve", "fix the bug"])

        # With the fix, the executor creates the usage file in a temp dir
        # (not in source_workspace). We intercept mkdtemp to control the
        # directory so we can pre-populate the usage file before run().
        tmpdir = Path(tempfile.mkdtemp(prefix="hermes-test-usage-"))
        try:
            usage_file = tmpdir / f".agent-os-usage-{job.id}.json"
            usage_file.write_text('{"prompt_tokens": 100, "completion_tokens": 50}')

            with patch("tempfile.mkdtemp", return_value=str(tmpdir)), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=b"done\n",
                    stderr=b"",
                )
                outcome = _make_executor().run(job, 1)

            self.assertEqual(outcome.evidence["usage"]["prompt_tokens"], 100)
            self.assertEqual(outcome.evidence["usage"]["completion_tokens"], 50)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_usage_file_missing_is_ok(self):
        """If hermes does not produce a usage file, that is not an error."""
        job = _make_job(command=["solve", "fix the bug"])
        # Ensure no stale usage file from a previous test
        usage_file = self.src / f".agent-os-usage-{job.id}.json"
        if usage_file.exists():
            usage_file.unlink()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            outcome = _make_executor().run(job, 1)
        self.assertEqual(outcome.evidence["usage"], {})

    def test_hermes_command_contains_required_flags(self):
        """The hermes command must contain -z, --usage-file, --profile, --reasoning, --in."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            _make_executor().run(job, 1)

        hermes_cmd = mock_run.call_args[0][0]
        self.assertIn("-z", hermes_cmd)
        self.assertIn("--usage-file", hermes_cmd)
        self.assertIn("--profile", hermes_cmd)
        self.assertIn("--reasoning", hermes_cmd)
        self.assertIn("--in", hermes_cmd)

    def test_workspace_passed_as_in_flag(self):
        """The source workspace must be passed via --in."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            _make_executor().run(job, 1)

        hermes_cmd = mock_run.call_args[0][0]
        in_idx = hermes_cmd.index("--in")
        self.assertEqual(hermes_cmd[in_idx + 1], str(self.src))

    def test_executor_name(self):
        """The executor must have the correct name."""
        executor = _make_executor()
        self.assertEqual(executor.name, "hermes-executor")

    def test_allowed_actions(self):
        """The executor must support the correct actions."""
        executor = _make_executor()
        self.assertIn("delegate_task", executor.allowed_actions)
        self.assertIn("run_agent", executor.allowed_actions)

    def test_invocations_recorded(self):
        """Each invocation must be recorded."""
        job = _make_job(command=["solve", "fix the bug"])
        executor = _make_executor()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            executor.run(job, 1)

        self.assertEqual(len(executor.invocations), 1)
        self.assertEqual(executor.invocations[0]["job_id"], "job-test")
        self.assertEqual(executor.invocations[0]["attempt"], 1)

    def test_prompt_is_joined_from_argv(self):
        """Multi-word prompts must be joined into a single string."""
        job = _make_job(command=["solve", "fix", "the", "failing", "test"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            _make_executor().run(job, 1)

        hermes_cmd = mock_run.call_args[0][0]
        z_idx = hermes_cmd.index("-z")
        self.assertEqual(hermes_cmd[z_idx + 1], "fix the failing test")

    def test_custom_profile_and_reasoning(self):
        """Custom profile and reasoning level must be passed through."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            executor = HermesExecutor(
                source_workspace=self.src,
                profile="my-personal-assistant",
                reasoning_level="max",
                hermes_binary="/fake/hermes",
            )
            executor.run(job, 1)

        hermes_cmd = mock_run.call_args[0][0]
        profile_idx = hermes_cmd.index("--profile")
        self.assertEqual(hermes_cmd[profile_idx + 1], "my-personal-assistant")
        reasoning_idx = hermes_cmd.index("--reasoning")
        self.assertEqual(hermes_cmd[reasoning_idx + 1], "max")


class HermesExecutorApprovalTest(unittest.TestCase):
    """The hermes executor must be gated by the approval system."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.src = TMP / "src"
        self.src.mkdir(exist_ok=True)

    def test_executor_name_matches_registry(self):
        """The executor name must match what the CLI registers."""
        executor = _make_executor()
        self.assertEqual(executor.name, "hermes-executor")

    def test_executor_is_not_registered_by_default(self):
        """The hermes executor must NOT be registered by default."""
        from agent_os.api import _EXECUTORS
        _EXECUTORS.clear()
        self.assertNotIn("hermes-executor", _EXECUTORS)

    def test_executor_can_be_registered(self):
        """The hermes executor can be explicitly registered."""
        from agent_os.api import _EXECUTORS, register_executor, unregister_executor
        _EXECUTORS.clear()
        try:
            executor = _make_executor()
            register_executor("hermes-executor", executor)
            self.assertIn("hermes-executor", _EXECUTORS)
            self.assertIs(_EXECUTORS["hermes-executor"], executor)
        finally:
            unregister_executor("hermes-executor")


class HermesBinaryResolutionTest(unittest.TestCase):
    """Tests for the _find_hermes helper."""

    def test_find_hermes_returns_none_when_not_found(self):
        """If hermes is not on PATH and not in known locations, return None."""
        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile", return_value=False):
                result = _find_hermes()
        self.assertIsNone(result)

    def test_find_hermes_finds_on_path(self):
        """If hermes is on PATH, return it."""
        with patch("shutil.which", return_value="/usr/bin/hermes"):
            result = _find_hermes()
        self.assertEqual(result, "/usr/bin/hermes")


class HermesExecutorBugFixTest(unittest.TestCase):
    """Tests for bug fixes: usage file paths, timeout handling, path conversion."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.src = TMP / "src"
        self.src.mkdir(exist_ok=True)

    def tearDown(self):
        # Clean up stale usage files that tests pre-create under self.src.
        for f in self.src.glob(".agent-os-usage-*.json"):
            f.unlink(missing_ok=True)

    def test_usage_file_read_from_windows_path(self):
        """If hermes.exe writes usage to the tmpdir, we must read it from there."""
        import tempfile
        job = _make_job(command=["solve", "fix the bug"])

        # Usage file now lives in a tmpdir (not source_workspace). Mock mkdtemp
        # so we know where the executor will look and can pre-populate the file.
        tmpdir = Path(tempfile.mkdtemp(prefix="hermes-bugfix-"))
        try:
            usage_file = tmpdir / f".agent-os-usage-{job.id}.json"
            usage_file.write_text('{"prompt_tokens": 200, "completion_tokens": 100}')

            with patch("tempfile.mkdtemp", return_value=str(tmpdir)), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=b"done\n",
                    stderr=b"",
                )
                outcome = _make_executor().run(job, 1)

            self.assertEqual(outcome.evidence["usage"]["prompt_tokens"], 200)
            self.assertEqual(outcome.evidence["usage"]["completion_tokens"], 100)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_timeout_captures_partial_output(self):
        """Timeout must capture partial stdout/stderr."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            # TimeoutExpired in Python 3.14 doesn't accept stdout/stderr kwargs
            exc = subprocess.TimeoutExpired(cmd="hermes", timeout=1)
            exc.stdout = b"partial output"
            exc.stderr = b"partial error"
            mock_run.side_effect = exc
            outcome = _make_executor(timeout=1).run(job, 1)
        self.assertEqual(outcome.status, "completed_missing_evidence")
        self.assertEqual(outcome.evidence.get("reason"), "timeout")
        self.assertIn("partial output", outcome.evidence.get("diff", ""))
        self.assertIn("partial error", outcome.evidence.get("diff", ""))

    def test_timeout_includes_timeout_seconds(self):
        """Timeout evidence must include the timeout duration."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="hermes", timeout=1)
            outcome = _make_executor(timeout=1).run(job, 1)
        self.assertEqual(outcome.evidence.get("timeout_seconds"), 1)

    def test_path_conversion_uses_wslpath(self):
        """When hermes_binary ends with .exe, convert_path must use wslpath."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            with patch("shutil.which", return_value="/usr/bin/wslpath"):
                with patch("agent_os.adapters.hermes_executor.subprocess.run") as mock_wsl:
                    # wslpath returns str, hermes returns bytes
                    def side_effect(cmd, **kwargs):
                        if "wslpath" in cmd:
                            return MagicMock(
                                stdout="C:\\Users\\Mehdi\\workspace\\usage.json\n",
                                returncode=0,
                            )
                        return MagicMock(
                            returncode=0,
                            stdout=b"done\n",
                            stderr=b"",
                        )
                    mock_wsl.side_effect = side_effect
                    executor = _make_executor(hermes_binary="/fake/hermes.exe")
                    outcome = executor.run(job, 1)
                    mock_wsl.assert_called()

    def test_path_conversion_fallback_without_wslpath(self):
        """When wslpath is not available, convert_path returns original path."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            with patch("shutil.which", return_value=None):
                executor = _make_executor(hermes_binary="/fake/hermes.exe")
                outcome = executor.run(job, 1)
                self.assertEqual(outcome.status, "completed_with_evidence")

    def test_model_flag_in_command(self):
        """The hermes command must include --model flag."""
        job = _make_job(command=["solve", "fix the bug"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"done\n",
                stderr=b"",
            )
            _make_executor().run(job, 1)
        hermes_cmd = mock_run.call_args[0][0]
        self.assertIn("--model", hermes_cmd)

    def test_usage_file_read_from_both_paths(self):
        """Usage file should be read from the tmpdir (WSL path)."""
        import tempfile
        job = _make_job(command=["solve", "fix the bug"])

        tmpdir = Path(tempfile.mkdtemp(prefix="hermes-both-paths-"))
        try:
            wsl_usage = tmpdir / f".agent-os-usage-{job.id}.json"
            wsl_usage.write_text('{"tokens": 42}')

            with patch("tempfile.mkdtemp", return_value=str(tmpdir)), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=b"done\n",
                    stderr=b"",
                )
                outcome = _make_executor().run(job, 1)

            self.assertEqual(outcome.evidence["usage"]["tokens"], 42)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
