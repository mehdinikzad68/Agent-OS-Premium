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
import os
import shutil
import signal
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
from ..paths import canonicalize, is_within


class SubprocessExecutor:
    name = "subprocess-executor"
    # Deliberately narrow: a generic command executor exposes the ability to
    # run anything, so it must be enabled by an explicit, reviewed decision.
    allowed_actions = frozenset({"run_command", "run_tests"})

    # Process-group control is POSIX-only. On a platform without it we cannot
    # honestly promise that a timeout leaves nothing running, so this adapter
    # refuses to run rather than silently under-killing. No Windows branch is
    # provided on purpose: it could never be exercised by the WSL-only test
    # suite, and untested cleanup code is worse than a clear refusal.
    supports_process_groups: bool = hasattr(os, "killpg")

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
        # The command is a canonical JSON argv string (see models.encode_command).
        # decode_command re-checks the shape after parsing and raises
        # CommandFormatError for anything unreadable - which is the migration
        # path: a row written before this fix fails closed with a message an
        # operator can act on, instead of handing Popen a string and dying with
        # FileNotFoundError, or a dict and dying with TypeError.
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

        command = argv
        self.invocations.append({"job_id": job.id, "attempt": attempt, "command": command})

        # 1. Create a disposable copy of the source workspace. Use Path.mkdir
        # with a unique name rather than tempfile.mkdtemp: mkdtemp creates the
        # dir with mode 0o700, which restricted sandboxes may refuse to write
        # into; a normal mkdir behaves like any harness-allowed directory.
        #
        # Refuse BEFORE creating anything: the copy follows symlinks by
        # default, so an escaping link would put outside content into a
        # directory the command can read and the evidence will publish.
        if self.source_workspace.exists():
            escaping = _find_escaping_links(self.source_workspace)
            if escaping:
                raise WorkerLostError(
                    "refusing to run: the source workspace contains symlinks "
                    f"that point outside it ({len(escaping)} found); the copy "
                    "would carry their contents into the run directory. "
                    "Remove them, or point --source-workspace elsewhere. "
                    "Offending paths: " + "; ".join(escaping[:10])
                )

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
        child_pid = None  # set the moment the child exists, even if Popen raises
        if not self.supports_process_groups:
            # Fail closed, before anything is started.
            shutil.rmtree(sandbox, ignore_errors=True)
            raise WorkerLostError(
                "subprocess-executor needs POSIX process groups to guarantee a "
                "timeout leaves nothing running; os.killpg is unavailable here"
            )
        try:
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                proc = subprocess.Popen(
                    command,
                    cwd=str(sandbox),
                    stdout=out_f,
                    stderr=err_f,
                    shell=False,
                    # The child becomes the leader of its OWN process group, so
                    # the whole tree can be signalled as one unit. Without this
                    # the grandchild inherits the parent's group and survives
                    # proc.kill(), which only ever signals the direct child.
                    start_new_session=True,
                )
                # Record the pid as soon as the child exists. `proc` alone is not
                # enough: Popen can raise AFTER the fork has already happened, and
                # a partially-assigned `proc` leaves us with a live process and no
                # handle on it - the one case where cleanup silently does nothing.
                child_pid = proc.pid
                try:
                    proc.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    _kill_process_tree(proc, child_pid)
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
            # `proc` may be None even though a child was forked, so the pid is
            # the reliable handle here.
            _kill_process_tree(proc, child_pid)
            self._write_meta(meta_path, command, started, -1, f"error:{e}")
            if not self.keep_workspace:
                shutil.rmtree(sandbox, ignore_errors=True)
            raise WorkerLostError(f"subprocess executor failed: {e}")
        finally:
            # KeyboardInterrupt and SystemExit derive from BaseException, so
            # the `except Exception` above cannot see them. Without this block
            # a Ctrl-C during wait() abandons a live process tree. This is the
            # only place that runs on every exit path, and it is NOT redundant
            # with the except branch: measured, removing only one of the two
            # still cleans up, and only removing both lets a grandchild live.
            if child_pid is not None and (proc is None or proc.poll() is None):
                _kill_process_tree(proc, child_pid)
                if proc is not None:
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass

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


def _kill_process_tree(proc, pid=None) -> None:
    """SIGKILL the whole process group the child leads.

    The child is started with start_new_session=True, so its pgid equals its
    pid and signalling the group reaches every descendant. SIGKILL rather than
    SIGTERM because the point of a timeout is that the work is already late;
    a child that traps SIGTERM would otherwise keep running.

    `pid` is passed separately because `proc` can be unusable exactly when
    cleanup matters most: Popen may raise after the fork, leaving a live
    process and no Popen object. Falling back to the raw pid keeps that case
    covered.

    Falls back to the single child if the group is already gone, so this is
    safe to call from a finally block on any exit path.
    """
    target = pid if pid is not None else getattr(proc, "pid", None)
    if target is None:
        return
    try:
        os.killpg(os.getpgid(target), signal.SIGKILL)
        return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    if proc is not None:
        try:
            proc.kill()
        except OSError:
            pass
    else:
        # no Popen object to fall back on; signal the pid directly
        try:
            os.kill(target, signal.SIGKILL)
        except OSError:
            pass


def _find_escaping_links(src: Path) -> list[str]:
    """Every symlink under `src` whose real target lies OUTSIDE `src`.

    shutil.copytree defaults to symlinks=False, which FOLLOWS a link and copies
    the target's contents. A link to ~/.ssh therefore lands inside the sandbox,
    where a command can read it and - because the executor publishes stdout in
    evidence, and /api/jobs/<id>/evidence returns it - the contents leave over
    HTTP. Measured before this guard existed: a link named innocently copied
    `id_rsa` and `credentials` into the run directory.

    Preserving the link instead (symlinks=True) is NOT a fix. Measured: a
    command reading through a preserved link still returns the target's
    contents, because the read happens with the server's own privileges. So the
    copy cannot be made safe by a flag - the run is refused instead.

    os.walk(followlinks=False) is used rather than a top-level iterdir(): a
    link nested at any depth must be found, and walk still REPORTS links (it
    just does not descend through them). is_within is the same predicate the
    Phase 1 project registry uses, so the notion of "inside" is one thing in
    this codebase - and it rejects a sibling that merely shares a prefix.

    A link whose target stays inside `src` is not reported: copying it is
    harmless, and refusing ordinary projects for a self-referential link would
    be a regression bought for nothing.
    """
    root = canonicalize(os.path.realpath(src))
    escaping: list[str] = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        for name in list(dirnames) + filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                continue
            # do not descend into a link we are about to reject or ignore
            if name in dirnames:
                dirnames.remove(name)
            target = os.path.realpath(p)
            if not is_within(root, canonicalize(target)):
                escaping.append(f"{p.relative_to(src)} -> {target}")
    return sorted(escaping)


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
