# Agent OS — Development Guide

## Architecture Overview

Agent OS is a deterministic local control plane for AI agents. The core
principle: **the only path from approval to execution is `dispatch()`**,
and dispatch runs policy validation **before** the executor is invoked.

```
UI (web/index.html) ─┐
CLI / scripts ───────┼─> HTTP API (token, loopback) ─> ControlService ─> SQLite
                     │         │                              │
                     │         └─ executor registry           └─ policy.py (pure, deny-first)
                     │                ├─ fake-executor
                     │                └─ subprocess-executor (gated, disposable copy)
                     │                └─ container-executor (Docker isolation)
```

## Project Structure

```
control-service/
  agent_os/
    models.py               domain types, manifest hashing, errors
    policy.py               pure validate_dispatch — no I/O, deny before dispatch
    store.py                SQLite truth + append-only events + migrations
    service.py              ControlService — the only path approval → dispatch
    api.py                  loopback JSON API + UI serving (token auth)
    cli.py                  serve / token / init / test entry points
    discovery.py            tool discovery (read-only, writes nothing)
    graphics.py             inline-SVG graphics library
    logging_setup.py        structured logging + CLI viewer
    paths.py                path validation and canonicalization
    adapters/
      fake.py               scriptable fake executor (tests/enforcement)
      subprocess_executor.py  real gated executor, disposable workspace
      container_executor.py   Docker-isolated executor
    web/
      index.html            single-file RTL dashboard (offline, no CDN)
  tests/                    618 tests (A1–A13 + CLI gates)
    live_server.py          shared harness: OS-chosen port, identity-checked readiness
  run_tests.py              file-writing test runner (sandbox-safe)
  e2e_verify.py             11-step product verification over real HTTP
  check_ui.py               UI structural validation (balance + handler wiring)
  pyproject.toml            zero dependencies, Python ≥ 3.11
```

## Key Design Decisions

### 1. Deny-Before-Dispatch

`policy.validate_dispatch()` is a pure function that returns `None` (allow)
or a denial reason string. It runs **before** the executor is invoked. This
is the core security guarantee.

### 2. Single-Use Approvals

`store.consume_approval()` is an atomic `UPDATE ... WHERE consumed_at IS NULL`.
A spent approval can never authorise a second execution.

### 3. Action-Bound Approvals

An approval is bound to one specific action (`ApprovalScope.action`). A grant
for `run_tests` cannot be used to dispatch a `deploy` job.

### 4. Manifest Hashing

The job's command, executor, workspace paths, and actions are hashed into
a `manifest_hash`. If any of these change, the approval is invalidated.

### 5. Append-Only Event Log

The `events` table is append-only. No update or delete. Duplicate `dedup_key`
values are ignored (idempotent replay).

### 6. Loopback-Only Binding

The server binds to `127.0.0.1` only. No LAN/network exposure. The UI shell
is public (no token), but every `/api/*` endpoint requires a token.

### 7. Zero Dependencies

The project uses only the Python standard library. No pip installs required.
This makes it auditable and portable.

## Running Tests

```bash
cd control-service

# Unit tests (618 tests)
python3 -B -m unittest discover -s tests -t .

# E2E verification (11 steps over real HTTP)
python3 -B e2e_verify.py

# UI structural validation
python3 -B check_ui.py

# All must exit 0
```

## Test Philosophy

- **Mutation testing**: Every security fix ships with a mutation check that
  proves the test goes red when the fix is removed.
- **HTTP proofs**: Behavioural claims are proven over real HTTP, not just
  unit tests.
- **No orphan servers**: The test harness uses OS-chosen ports and
  identity-checked readiness probes.

## Adding a New Executor

1. Create `agent_os/adapters/my_executor.py`
2. Implement the `execute(job, evidence) -> WorkerOutcome` interface
3. Register in `agent_os/api.py`:
   ```python
   from .adapters.my_executor import MyExecutor
   register_executor("my-executor", MyExecutor())
   ```
4. Add tests in `tests/test_my_executor.py`
5. Update the executor registry documentation

## Adding a New Policy Check

1. Add the check in `policy.validate_dispatch()`
2. Add a test in `test_phase5.py` or a new test file
3. Add a mutation check that removes the test and verifies failure

## Logging

Logs are written to `.logs/agent-os-<date>.jsonl`. Console output is
suppressed unless `AGENT_OS_DEBUG=1` is set.

View logs with:
```bash
python -m agent_os.logview
```

## Security Model

See [docs/10-گزارش-تست-امنیتی-و-نفوذ-Agent-OS.md](../docs/10-گزارش-تست-امنیتی-و-نفوذ-Agent-OS.md)
for the full security and penetration test report.

## Contributing

1. Create a feature branch
2. Write tests first (TDD)
3. Implement the feature
4. Run all tests: `python3 -B -m unittest discover -s tests -t .`
5. Run E2E: `python3 -B e2e_verify.py`
6. Run mutation checks for security fixes
7. Update documentation
8. Submit a pull request

## License

MIT
