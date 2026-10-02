# Phase 6 — Design Document

**Date:** 2026-10-02
**Status:** Approved by owner, ready for implementation
**Goal:** Replace the subprocess executor's OS-level access with a Docker container that has no access to anything except the mounted project directory.

---

## 1. Problem statement

F2 (PARTIAL): The subprocess executor runs commands with the server's own OS privileges. A command can read any file the server can read, write anywhere, and access the network. The workspace copy is a working directory, not a security boundary.

**Phase 6 must prove:** A command running through the new executor cannot read, write, or reach anything outside the mounted project directory.

---

## 2. Architecture decision

### Chosen approach: Docker container with minimal mounts

Each job execution creates a fresh Docker container that:
- Has the project directory mounted as its only writable path
- Has no network access
- Has no access to the Docker socket
- Runs as a non-root user
- Has a read-only root filesystem
- Is automatically removed after execution

### Why Docker (not Linux namespaces/cgroups directly)

| Criterion | Docker | Raw namespaces |
|-----------|--------|----------------|
| Isolation strength | Kernel-level (same) | Kernel-level (same) |
| Implementation complexity | Low — CLI is the API | High — need to manage namespaces, cgroups, chroot |
| Testability | Easy — `docker run` is deterministic | Hard — need to verify namespace setup |
| Maintainability | Well-documented, widely understood | Custom code, easy to get wrong |
| Rollback | Remove the executor file | Same |

Docker is the pragmatic choice: same isolation, far less code, easier to audit.

### Why not extend the subprocess executor

The subprocess executor copies the workspace to a temp dir and runs there. That temp dir is still on the host filesystem, with the host's permissions. The only way to bound it is to not use the host filesystem at all — which means a container.

---

## 3. Container specification

### Base image

```
python:3.14-slim
```

**Rationale:** Minimal Debian-based image with Python pre-installed. No compilers, no package managers, no unnecessary tools. If a project needs a different runtime, the image can be overridden per-project in a future phase.

### Docker run flags

| Flag | Purpose |
|------|---------|
| `--rm` | Auto-remove container after exit |
| `--network none` | No network access |
| `--read-only` | Root filesystem is read-only |
| `--tmpfs /tmp` | Writable tmpfs for temporary files |
| `--cap-drop ALL` | Drop all Linux capabilities |
| `--security-opt no-new-privileges` | Prevent privilege escalation |
| `--user 1000:1000` | Run as non-root user |
| `--mount type=bind,source=<project>,target=/workspace` | Mount project directory |
| `--workdir /workspace` | Set working directory |
| `--memory 512m` | Memory limit |
| `--cpus 1.0` | CPU limit |

### What the container CAN do

- Read files in `/workspace` (the mounted project)
- Write files in `/workspace` (the mounted project)
- Write to `/tmp` (tmpfs, ephemeral)
- Execute commands installed in the base image

### What the container CANNOT do

- Read files outside `/workspace` (not mounted)
- Write files outside `/workspace` (read-only root + no other mounts)
- Access the network (`--network none`)
- Access the Docker socket (not mounted)
- Escalate privileges (`no-new-privileges`, `cap-drop ALL`)
- See other containers (no Docker access)

---

## 4. Executor design

### File: `control-service/agent_os/adapters/container_executor.py`

```python
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
    ):
        ...
    
    def run(self, job: Job, attempt: int) -> WorkerOutcome:
        # 1. Decode and validate command
        # 2. Build docker run flags
        # 3. Execute: docker run --rm --network none --read-only ...
        # 4. Capture stdout/stderr
        # 5. Return WorkerOutcome
        ...
```

### Key implementation details

1. **Command execution:** `docker run [flags] <image> <command...>` — the command is passed as arguments to `docker run`, not shell-interpreted.

2. **Workspace mount:** The project directory is mounted at `/workspace` inside the container. The command runs with `--workdir /workspace`.

3. **Output capture:** `subprocess.run` captures stdout/stderr. The output is stored in the evidence dict, same as the subprocess executor.

4. **Timeout:** `subprocess.run(timeout=...)` kills the `docker run` process. The container is auto-removed by `--rm`.

5. **Error handling:** If `docker run` fails (non-zero exit), the error is captured and returned as `completed_missing_evidence`.

6. **No shell injection:** The command is passed as a list to `subprocess.run` with `shell=False`. Docker receives it as argv, not as a shell string.

---

## 5. Integration with approval gate

The container executor is registered in the CLI, gated behind an explicit flag (same pattern as the subprocess executor):

```python
if args.enable_container:
    from .adapters.container_executor import ContainerExecutor
    register_executor(
        "container-executor",
        ContainerExecutor(
            source_workspace=args.source_workspace,
            image=args.container_image,
            timeout_seconds=args.container_timeout,
        ),
    )
```

The approval gate (Phase 5) is unchanged: `dispatch()` calls `validate_dispatch()` before `adapter.run()`. The container executor is just another adapter.

---

## 6. Test strategy

### Unit tests (mock Docker)

File: `tests/test_container_executor.py`

Test that:
- Command is executed with correct Docker flags
- Workspace is mounted correctly
- Output is captured
- Timeout is enforced
- Errors are handled

### Security boundary tests (real Docker)

File: `tests/test_container_boundary.py`

Test that:
- A command cannot read `/etc/passwd` (outside workspace)
- A command cannot write to `/` (read-only root)
- A command cannot access the network (`curl` fails)
- A command cannot see the Docker socket
- A command cannot escalate privileges

### Proof script

File: `p6_proof.py`

End-to-end proof over real HTTP:
1. Start server with container executor
2. Create a test project
3. Create a job
4. Approve it
5. Dispatch it
6. Verify the command ran and output was captured
7. Verify the container was removed

Anti-proof: Remove one security flag (e.g., `--network none`) and verify the proof fails.

---

## 7. Files to create/modify

| File | Action | Purpose |
|------|--------|---------|
| `agent_os/adapters/container_executor.py` | Create | New executor |
| `tests/test_container_executor.py` | Create | Unit tests |
| `tests/test_container_boundary.py` | Create | Security tests |
| `p6_proof.py` | Create | Proof script |
| `p6_mutation_check.py` | Create | Anti-proof |
| `agent_os/cli.py` | Modify | Add `--enable-container` flag |
| `FINDINGS.md` | Modify | F2 → CLOSED |
| `READINESS.md` | Modify | Phase 6 → complete |
| `README.md` | Modify | Document container executor |

---

## 8. Risks and mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Docker daemon not running | Low | Check at startup, fail with clear message |
| Image not pulled | Low | `docker pull` in executor init, with timeout |
| WSL2 mount performance | Medium | Acceptable for test workloads; document limitation |
| Container escape | Very low | Multiple layers: read-only, no network, no caps, non-root |
| Docker socket exposure | None | Not mounted by default; test verifies |

---

## 9. Exit criteria

Phase 6 is complete when:

1. `container_executor.py` exists and is registered behind `--enable-container`
2. All 449 existing tests still pass
3. New unit tests pass (mock Docker)
4. Security boundary tests pass (real Docker)
5. `p6_proof.py` reports PROVEN
6. `p6_mutation_check.py` reports RED (anti-proof)
7. F2 is marked CLOSED in FINDINGS.md
8. READINESS.md shows Phase 6 as complete
