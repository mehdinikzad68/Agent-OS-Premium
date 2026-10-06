"""Container executor — runs commands inside a Docker container with strict isolation.

This is the Phase 6 executor that closes F2: instead of running commands with
the server's own OS privileges, each execution happens inside a fresh Docker
container that has NO access to anything except the mounted project directory.

Isolation enforced by Docker:
- `--network none` — no network access
- `--read-only` — root filesystem is read-only
- `--tmpfs /tmp` — writable tmpfs for temporary files
- `--cap-drop ALL` — no Linux capabilities
- `--security-opt no-new-privileges` — no privilege escalation
- `--user 1000:1000` — non-root user
- `--rm` — auto-remove after exit
- Only a DISPOSABLE COPY of the project is mounted at /workspace (H2):
  the real source directory is never mounted, so a destructive command
  can only destroy the copy

GATED: this adapter is NOT registered by default. The CLI registers it only
when the caller passes an explicit flag (--enable-container).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from ..models import (
    CommandFormatError,
    Job,
    WorkerLostError,
    WorkerOutcome,
    decode_command,
)

_log = logging.getLogger(__name__)

# Cleanup failures are recorded here as well as logged. A container that
# could not be removed is a fact about the machine's state, and the only way
# it can be acted on is if it is retrievable without attaching to a process
# that has already exited.
cleanup_failures: list[dict] = []
_CLEANUP_LOG_CAP = 200


def _discard_container(container_name: str, why: str) -> bool:
    """Remove a Docker container, and never let a failed remove disappear.

    `docker rm -f` can fail if the container is already gone, or if Docker
    is in a bad state. The failure is logged and recorded so it is visible
    afterwards, but it does not fail the run — the outcome is already known.
    """
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=30,
        )
        return True
    except Exception as e:
        rec = {
            "container": container_name,
            "why": why,
            "error": f"{type(e).__name__}: {e}",
        }
        _log.warning("container cleanup failed: %s", rec)
        cleanup_failures.append(rec)
        del cleanup_failures[:-_CLEANUP_LOG_CAP]
        return False


def _discard_sandbox_dir(sandbox: Path, why: str) -> bool:
    """Delete a run copy; a failed deletion is recorded, never swallowed.

    Same contract as the subprocess executor's _discard_sandbox: a copy
    that cannot be removed is a fact about the machine and must be
    retrievable, but it never fails a run whose outcome is already known.
    """
    try:
        shutil.rmtree(sandbox)
        return True
    except OSError as e:
        rec = {
            "sandbox": str(sandbox),
            "why": why,
            "error": f"{type(e).__name__}: {e}",
            "still_present": sandbox.exists(),
        }
        _log.warning("sandbox cleanup failed: %s", rec)
        cleanup_failures.append(rec)
        del cleanup_failures[:-_CLEANUP_LOG_CAP]
        return False


def failed_cleanups() -> list[dict]:
    """Cleanup failures recorded so far, newest last. Read-only."""
    return list(cleanup_failures)


def clear_failed_cleanups() -> None:
    cleanup_failures.clear()


class ContainerExecutor:
    name = "container-executor"
    allowed_actions = frozenset({"run_command", "run_tests"})

    def __init__(
        self,
        source_workspace: str | Path,
        image: str = "python:3.14-slim",
        timeout_seconds: int = 120,
        memory_limit: str = "512m",
        cpu_limit: str = "1.0",
        keep_workspace: bool = False,
        sandbox_root: str | Path | None = None,
    ):
        self.source_workspace = Path(source_workspace)
        self.sandbox_root = Path(sandbox_root) if sandbox_root is not None else None
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.keep_workspace = keep_workspace
        self.invocations: list[dict] = []

    def run(self, job: Job, attempt: int) -> WorkerOutcome:
        # Decode and validate the stored command (same as subprocess executor)
        try:
            argv = decode_command(getattr(job, "command", None))
        except CommandFormatError as e:
            return WorkerOutcome(
                status="completed_missing_evidence",
                evidence={
                    "error": f"unreadable stored command: {e}",
                    "diff": "",
                    "test_report": "",
                },
            )
        if not argv:
            return WorkerOutcome(
                status="completed_missing_evidence",
                evidence={
                    "error": "no command specified; set job.command before dispatch",
                    "diff": "",
                    "test_report": "",
                },
            )

        command = argv

        # H2 (review 2026-10-05): mount a DISPOSABLE COPY, never the real
        # source. The copy still gives commands a writable /workspace (test
        # output, build artifacts), but `rm -rf /workspace` can then only
        # destroy the copy - the operator's project directory is never
        # mounted, so this executor honours the same "the original is never
        # modified" rule as the subprocess executor.
        sandbox: Path | None = None
        try:
            run_root = (
                self.sandbox_root
                if self.sandbox_root is not None
                else Path(tempfile.mkdtemp(prefix="agent-os-ctx-"))
            )
            if self.sandbox_root is not None:
                run_root.mkdir(parents=True, exist_ok=True)
            sandbox = run_root / f"agent-os-run-{uuid.uuid4().hex[:12]}"
            shutil.copytree(self.source_workspace, sandbox, symlinks=True)
        except OSError as e:
            if sandbox is not None:
                _discard_sandbox_dir(sandbox, "copy-failed")
            return WorkerOutcome(
                status="completed_missing_evidence",
                evidence={
                    "diff": "",
                    "test_report": "",
                    "error": f"workspace copy failed: {e}",
                },
            )

        self.invocations.append({"job_id": job.id, "attempt": attempt, "command": command})

        # Generate a unique container name for this run
        container_name = f"agent-os-run-{uuid.uuid4().hex[:12]}"

        # Build the docker run command
        # The DISPOSABLE COPY is mounted at /workspace inside the container.
        # The command runs with --workdir /workspace.
        docker_cmd = [
            "docker", "run",
            "--name", container_name,
            "--rm",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "1000:1000",
            "--memory", self.memory_limit,
            "--cpus", self.cpu_limit,
            "--mount", f"type=bind,source={sandbox},target=/workspace",
            "--workdir", "/workspace",
            self.image,
            *command,
        ]

        started = time.monotonic()
        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            # Timeout: kill the container
            _discard_container(container_name, "timeout")
            if not self.keep_workspace:
                _discard_sandbox_dir(sandbox, "timeout")
            return WorkerOutcome(
                status="completed_missing_evidence",
                evidence={
                    "diff": "",
                    "test_report": "",
                    "reason": "timeout",
                    "container": container_name if self.keep_workspace else "",
                },
            )
        except Exception as e:
            # Executor itself broke: unknown outcome
            _discard_container(container_name, "executor-error")
            if not self.keep_workspace:
                _discard_sandbox_dir(sandbox, "executor-error")
            raise WorkerLostError(f"container executor failed: {e}")

        duration = round(time.monotonic() - started, 3)
        exit_code = result.returncode
        stdout_txt = result.stdout.decode("utf-8", errors="replace")
        stderr_txt = result.stderr.decode("utf-8", errors="replace")

        # Evidence: same format as subprocess executor
        evidence = {
            "diff": f"exit_code={exit_code}\n\n--- stdout ---\n{stdout_txt}\n\n--- stderr ---\n{stderr_txt}",
            "test_report": _detect_test_report(stdout_txt, stderr_txt, exit_code),
            "exit_code": exit_code,
            "container": container_name if self.keep_workspace else "",
            "sandbox": str(sandbox) if self.keep_workspace else "",
            "duration_seconds": duration,
        }

        # Dispose the copy (H2): the real source was never mounted, and the
        # copy is single-use unless keep_workspace asks to retain it.
        if not self.keep_workspace:
            _discard_sandbox_dir(sandbox, "completed")

        # exit 0 with a recognizable passing-test report => verified
        if exit_code == 0 and evidence["test_report"]:
            return WorkerOutcome(status="completed_with_evidence", evidence=evidence)
        return WorkerOutcome(status="completed_missing_evidence", evidence=evidence)


# M4 (B2): detection lives once, in agent_os/evidence.py, where both
# executors share it; framework summaries are tried before the
# unchanged generic markers.
from ..evidence import detect_test_report as _detect_test_report
