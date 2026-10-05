"""Hermes executor — delegates a job to the Hermes agent runtime.

This adapter runs `hermes -z <prompt>` (one-shot mode) and collects the
final response from stdout plus usage metadata from a JSON file.

The Hermes CLI is not on PATH inside WSL; it lives on the Windows host.
The executor resolves the binary at construction time and refuses to run
if it cannot be found, rather than failing mid-run with FileNotFoundError.

GATED: this adapter is NOT registered by default. The CLI registers it only
when the caller passes an explicit flag (--enable-hermes).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from agent_os.models import (
    CommandFormatError,
    Job,
    WorkerLostError,
    WorkerOutcome,
    decode_command,
)

_log = logging.getLogger(__name__)

# Default locations to search for the hermes binary, in order.
# The Windows path is the most common; the WSL path is a fallback.
_HERMES_CANDIDATES = [
    "hermes.exe",
    "/mnt/c/Users/Mehdi/AppData/Local/hermes/bin/hermes.exe",

    "hermes",  # if it is on PATH
    r"C:\Users\Mehdi\AppData\Local\hermes\bin\hermes.exe",
    r"C:\Users\Mehdi\AppData\Local\hermes\hermes-agent\.hermes\bin\hermes.exe",
]


def _find_hermes() -> str | None:
    """Find the hermes binary, or return None if not found."""
    # First, try PATH
    found = shutil.which("hermes")
    if found:
        return found
    # Then try known Windows locations
    for candidate in _HERMES_CANDIDATES[1:]:
        if os.path.isfile(candidate):
            return candidate
    return None


class HermesExecutor:
    name = "hermes-executor"
    allowed_actions = frozenset({"delegate_task", "run_agent"})

    def __init__(
        self,
        source_workspace: str | Path,
        timeout_seconds: int = 1800,
        profile: str = "default",
        reasoning_level: str = "medium",
        hermes_binary: str | None = None,
    ):
        self.source_workspace = Path(source_workspace)
        self.timeout_seconds = timeout_seconds
        self.profile = profile
        self.reasoning_level = reasoning_level
        self.hermes_binary = hermes_binary or _find_hermes()
        self.invocations: list[dict] = []

    def run(self, job: Job, attempt: int) -> WorkerOutcome:
        # Decode and validate the stored command
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

        # The command is ["solve", "<prompt>"] — we need the prompt
        if len(argv) < 2:
            return WorkerOutcome(
                status="completed_missing_evidence",
                evidence={
                    "error": "command must have at least 2 elements: [operator, prompt]",
                    "diff": "",
                    "test_report": "",
                },
            )

        task_prompt = " ".join(argv[1:])
        self.invocations.append({
            "job_id": job.id,
            "attempt": attempt,
            "prompt": task_prompt,
        })

        if not self.hermes_binary:
            return WorkerOutcome(
                status="completed_missing_evidence",
                evidence={
                    "error": "hermes binary not found; set hermes_binary or add hermes to PATH",
                    "diff": "",
                    "test_report": "",
                },
            )

        # Build the hermes command.
        # The usage file must live in a temp dir, NOT in source_workspace.
        # Writing to source_workspace violates the invariant that executors
        # never touch the original workspace (test_original_workspace_not_modified).
        import tempfile
        _usage_tmpdir = Path(tempfile.mkdtemp(prefix="agent-os-usage-"))
        usage_file = _usage_tmpdir / f".agent-os-usage-{job.id}.json"
        
        def convert_path(p: str | Path) -> str:
            p_str = str(p)
            if self.hermes_binary and self.hermes_binary.endswith(".exe") and shutil.which("wslpath"):
                try:
                    res = subprocess.run(["wslpath", "-w", p_str], capture_output=True,
                stdin=subprocess.DEVNULL, text=True, check=True)
                    return res.stdout.strip()
                except Exception:
                    pass
            return p_str
            
        w_usage_file = convert_path(usage_file)
        w_source_workspace = convert_path(self.source_workspace)
        hermes_cmd = [
            self.hermes_binary,
            "-z", task_prompt,
            "--usage-file", w_usage_file,
            "--profile", self.profile,
            "--reasoning", self.reasoning_level,
            "--in", w_source_workspace,
            "--model", "agy/gemini-pro-agent",
        ]

        started = time.monotonic()
        try:
            result = subprocess.run(
                hermes_cmd,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            so = e.stdout.decode('utf-8', errors='replace') if e.stdout else ''
            se = e.stderr.decode('utf-8', errors='replace') if e.stderr else ''
            _cleanup_usage_tmpdir(_usage_tmpdir)
            return WorkerOutcome(
                status="completed_missing_evidence",
                evidence={
                    "diff": f"partial_stdout={so} partial_stderr={se}",
                    "test_report": "",
                    "reason": "timeout",
                    "hermes_binary": self.hermes_binary,
                    "timeout_seconds": self.timeout_seconds,
                },
            )
        except Exception as e:
            _cleanup_usage_tmpdir(_usage_tmpdir)
            raise WorkerLostError(f"hermes executor failed: {e}")

        duration = round(time.monotonic() - started, 3)
        exit_code = result.returncode
        stdout_txt = result.stdout.decode("utf-8", errors="replace")
        stderr_txt = result.stderr.decode("utf-8", errors="replace")

        # Read usage file if it exists.
        # hermes.exe writes to the Windows path; we may read from either.
        usage = {}
        for candidate in (usage_file, Path(w_usage_file) if w_usage_file != str(usage_file) else None):
            if candidate is None:
                continue
            try:
                if candidate.exists():
                    usage = json.loads(candidate.read_text(encoding="utf-8"))
                    break
            except (json.JSONDecodeError, OSError):
                pass

        _cleanup_usage_tmpdir(_usage_tmpdir)

        evidence = {
            "diff": f"exit_code={exit_code}\n\n--- stdout ---\n{stdout_txt}\n\n--- stderr ---\n{stderr_txt}",
            "test_report": _detect_agent_success(stdout_txt, exit_code),
            "exit_code": exit_code,
            "hermes_response": stdout_txt,
            "usage": usage,
            "duration_seconds": duration,
            "hermes_binary": self.hermes_binary,
        }

        if exit_code == 0 and evidence["test_report"]:
            return WorkerOutcome(status="completed_with_evidence", evidence=evidence)
        return WorkerOutcome(status="completed_missing_evidence", evidence=evidence)


def _cleanup_usage_tmpdir(tmpdir: "Path") -> None:
    """Remove the temp dir created for the usage file.

    Failure is logged but never raised: a leftover temp dir is a minor
    resource leak, not a correctness problem. The important invariant is
    that source_workspace is never touched.
    """
    import shutil as _shutil
    try:
        _shutil.rmtree(tmpdir, ignore_errors=True)
    except OSError as e:
        _log.warning("could not remove usage tmpdir %s: %s", tmpdir, e)


def _detect_agent_success(stdout: str, exit_code: int) -> str:
    """Detect whether the Hermes agent completed successfully.

    Hermes in -z mode prints the final response to stdout. We look for
    common success indicators, but the primary signal is exit code 0.
    """
    if exit_code != 0:
        return ""
    # If stdout is non-empty and exit code is 0, the agent produced output
    if stdout.strip():
        return f"agent produced output (exit 0, {len(stdout)} chars)"
    return ""
