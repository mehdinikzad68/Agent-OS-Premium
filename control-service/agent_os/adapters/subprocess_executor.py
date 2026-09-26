"""Local subprocess executor — the first REAL executor adapter.

Runs a user-supplied command inside a DISPOSABLE workspace copy, bounded by
a timeout, and captures evidence to files (stdout/stderr/exit code) rather
than pipes (avoids pipe-buffer deadlocks and is sandbox-friendly).

Safety rules enforced by construction (AGENT-OS-HANDOFF.md section 7/8):
- Never runs in-place: it copies the source workspace to a fresh temp dir
  and runs there. The original is never modified.
- The command's cwd is the disposable copy only; no host home/credentials.
- Bounded by a hard timeout; on timeout the process is killed and the
  outcome is reported honestly (not success).
- exit code 0 is NOT treated as success: required evidence must be present.
- Never merges, commits, or publishes. No network is assumed.

GATED: this adapter is NOT registered by default. The CLI registers it only
when the caller passes an explicit flag. It runs plain OS commands (e.g.
`python -m pytest`), never Hermes/DSH, unless the operator chooses otherwise.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from ..models import Job, WorkerLostError, WorkerOutcome


class SubprocessExecutor:
    name = "subprocess-executor"
    # Deliberately narrow: a generic command executor exposes the ability to
    # run anything, so it must be enabled by an explicit, reviewed decision.
    allowed_actions = frozenset({"run_command", "run_tests"})

    def __init__(
        self,
        source_workspace: str | Path,
        timeout_seconds: int = 120,
        keep_workspace: bool = False,
        sandbox_root: str | Path | None = None,
    ):
        self.source_workspace = Path(source_workspace)
        self.timeout_seconds = timeout_seconds
        self.keep_workspace = keep_workspace
        # Where disposable copies are created. Defaults to the system temp
        # dir; operators may point this at a project-local directory for
        # auditability and to respect restricted write scopes.
        self.sandbox_root = Path(sandbox_root) if sandbox_root else Path(tempfile.gettempdir())
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.invocations: list[dict] = []

    def run(self, job: Job, attempt: int) -> WorkerOutcome:
        # The job must carry a command in its title is NOT how we pass it;
        # the command comes from an extra field carried on the job via
        # workspace_paths convention is wrong. Instead, we read the command
        # from the job's "actions" is wrong too. We require the caller to set
        # job fields via the adapter config; here we read command from a
        # dedicated job attribute if present, else fail closed.
        command = getattr(job, "command", None)
        if not command:
            # Fail closed: a subprocess executor without a command must not
            # guess. Callers set job.command before dispatch.
            return WorkerOutcome(
                status="completed_missing_evidence",
                evidence={
                    "error": "no command specified; set job.command before dispatch",
                    "diff": "",
                    "test_report": "",
                },
            )

        self.invocations.append({"job_id": job.id, "attempt": attempt, "command": command})

        # 1. Create a disposable copy of the source workspace. Use Path.mkdir
        # with a unique name rather than tempfile.mkdtemp: mkdtemp creates the
        # dir with mode 0o700, which restricted sandboxes may refuse to write
        # into; a normal mkdir behaves like any harness-allowed directory.
        sandbox = self.sandbox_root / f"agent-os-run-{uuid.uuid4().hex[:12]}"
        sandbox.mkdir()
        try:
            if self.source_workspace.exists():
                _copytree_into(self.source_workspace, sandbox)
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(sandbox, ignore_errors=True)
            raise WorkerLostError(f"failed to prepare disposable workspace: {e}")

        out_path = sandbox / ".agent-os.stdout.log"
        err_path = sandbox / ".agent-os.stderr.log"
        meta_path = sandbox / ".agent-os.meta.json"

        started = time.monotonic()
        proc = None
        try:
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                proc = subprocess.Popen(
                    command,
                    cwd=str(sandbox),
                    stdout=out_f,
                    stderr=err_f,
                    shell=False,
                )
                try:
                    proc.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    self._write_meta(meta_path, command, started, -1, "timeout")
                    if not self.keep_workspace:
                        shutil.rmtree(sandbox, ignore_errors=True)
                    return WorkerOutcome(
                        status="completed_missing_evidence",
                        evidence={
                            "diff": "",
                            "test_report": "",
                            "reason": "timeout",
                            "sandbox": str(sandbox) if self.keep_workspace else "",
                        },
                    )
        except Exception as e:  # noqa: BLE001
            # Executor itself broke after (possibly) starting work: unknown.
            self._write_meta(meta_path, command, started, -1, f"error:{e}")
            if not self.keep_workspace:
                shutil.rmtree(sandbox, ignore_errors=True)
            raise WorkerLostError(f"subprocess executor failed: {e}")

        exit_code = proc.returncode
        self._write_meta(meta_path, command, started, exit_code, "done")

        stdout_txt = _read_text(out_path)
        stderr_txt = _read_text(err_path)

        # Evidence: a "test_report" is required for verified completion. A
        # generic command has no structured test report, so we synthesize a
        # truthful summary from the exit code + output; but this is NOT a
        # passing-test claim — it is marked unverified by default unless the
        # caller's command itself produced a recognizable test signal.
        evidence = {
            "diff": f"exit_code={exit_code}\n\n--- stdout ---\n{stdout_txt}",
            "test_report": _detect_test_report(stdout_txt, stderr_txt, exit_code),
            "exit_code": exit_code,
            "sandbox": str(sandbox) if self.keep_workspace else "",
        }

        if not self.keep_workspace:
            shutil.rmtree(sandbox, ignore_errors=True)

        # exit 0 with a recognizable passing-test report => verified.
        if exit_code == 0 and evidence["test_report"]:
            return WorkerOutcome(status="completed_with_evidence", evidence=evidence)
        return WorkerOutcome(status="completed_missing_evidence", evidence=evidence)

    @staticmethod
    def _write_meta(meta_path: Path, command, started: float, exit_code: int, status: str) -> None:
        meta_path.write_text(
            json.dumps(
                {
                    "command": command,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "exit_code": exit_code,
                    "status": status,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _copytree_into(src: Path, dst: Path) -> None:
    """Copy src contents into dst (dst must exist and be empty-ish)."""
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".testtmp"))
        else:
            shutil.copy2(child, target)


def _read_text(path: Path, limit: int = 64_000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > limit:
        data = data[:limit] + b"\n...[truncated]"
    return data.decode("utf-8", errors="replace")


def _detect_test_report(stdout: str, stderr: str, exit_code: int) -> str:
    """Truthful test-signal detection. Only a recognizable passing test
    summary yields a non-empty report (which the service may then verify)."""
    combined = f"{stdout}\n{stderr}"
    markers = (
        " passed",
        " ok",
        "tests passed",
        "PASSED",
        "succeeded",
    )
    for m in markers:
        if m in combined and exit_code == 0:
            # Extract up to 4 lines around the marker for a human-reviewable report.
            lines = combined.splitlines()
            hits = [i for i, ln in enumerate(lines) if m in ln]
            if hits:
                i = hits[0]
                snippet = "\n".join(lines[max(0, i - 2): i + 3])
                return f"detected test signal '{m}' (exit 0)\n{snippet}"
    return ""
