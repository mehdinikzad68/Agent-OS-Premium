# Agent OS — Mission Control (v0.2.0)

A **personal, local control plane for AI agents**: deterministic state, human-only
approvals, deny-before-dispatch enforcement, durable audit trail, and a built-in
web dashboard. Zero dependencies — Python standard library only.

> **Status: locally testable product, single-user, pre-integration.**
> The dashboard, API, approval enforcement, subprocess executor, durable
> evidence and honest event ingestion are implemented and tested
> (643 unit tests + 11-step E2E, green). Hermes/DSH/Antigravity are **not yet
> integrated** (separately gated by design).
> Honest limits: see [READINESS.md](READINESS.md).

## Quick start

```bat
cd control-service
python3 -m agent_os.cli token          # generate a token
export AGENT_OS_TOKEN=<paste token>
python3 -m agent_os.cli serve --db mission-control.db
# open http://127.0.0.1:8470/ , paste the token, press اتصال
```

Bind is **loopback-only** (`127.0.0.1`) and `serve` **refuses to start** without a
token unless `--insecure` is passed (dev only).

## Verify a release

```bash
cd control-service
python3 run_tests.py      # 643 tests -> .test-results.txt
python3 e2e_verify.py     # 11-step product E2E -> e2e-result.txt
python3 check_ui.py       # UI structural validation
```

Both write file-based results (sandbox-safe). Exit code 0 = pass.

## What it enforces (all tested)

| # | Guarantee | Test |
|---|---|---|
| A1 | Restart preserves missions/approvals/event history | `test_a1_*` + E2E step 10 |
| A2 | Expired approval / unapproved destination / amended manifest refused **before** dispatch | `test_a2_*` + E2E step 8 |
| A3 | Planner/worker can never self-approve; tool inventory fixed | `test_a3_*` |
| A4 | Missing test evidence never becomes verified completion | `test_a4_*` |
| A5 | Lost worker = `interrupted/unknown` until human reconcile; no auto-rerun | `test_a5_*` |
| A6 | Duplicate dispatch / event replay = zero duplicate actions | `test_a6_*` + E2E step 7 |
| A7 | Knowledge edit on stale revision raises conflict | `test_a7_*` |
| A8 | Token auth fail-closed; loopback-only; UI shell public, API protected | `test_api_*` |
| A9 | Disposable workspace executor: never touches source, timeout = not success | `test_subprocess_*` |
| A10 | Evidence durable in event log + served by API; oversized bodies refused (413) | `test_evidence_*`, `test_oversized_body_*` + E2E step 11 |
| A11 | An approval is **single-use**: spent atomically on first dispatch, and a spent approval can never authorise another execution | `test_phase5.py` (single-use) + `p5_proof.py` |
| A12 | An approval is **bound to one action**, not just a ceiling of actions | `test_phase5.py` (action binding) |
| A13 | A grant **survives a restart** and is still usable, then still single-use | `test_phase5.py::RestartDurabilityTest` |

## Architecture (one paragraph)

A deterministic `ControlService` owns an SQLite store (WAL, append-only event log,
schema-versioned migrations). The **only** path from approval to execution is
`dispatch()`: the A6 idempotency check answers a replay of a finished job
first, then pure `validate_dispatch()` policy runs (deny → 409, executor never
invoked; this is where a missing, expired, mismatched or already-consumed
approval is refused), then the approval
is spent atomically (the single-winner gate: of two concurrent dispatches
over one approval exactly one may proceed), then the dispatch intent is
persisted, then the registered executor runs, then evidence is verified before
any state becomes `completed_verified`. HTTP is a thin loopback adapter (`agent_os/api.py`);
executors live behind a named registry — `fake-executor` by default, the real
`subprocess-executor` only with explicit `--enable-subprocess`.

```
UI (web/index.html) ─┐
CLI / scripts ───────┼─> HTTP API (token, loopback) ─> ControlService ─> SQLite
                     │         │                              │
                     │         └─ executor registry           └─ policy.py (pure, deny-first)
                     │                ├─ fake-executor
                     │                └─ subprocess-executor (gated, disposable copy)
```

## Layout

```
agent_os/
  models.py               domain types, manifest hashing, errors
  policy.py               pure validate_dispatch — no I/O, deny before dispatch
  store.py                SQLite truth + append-only events + migrations
  service.py              ControlService — the only path approval → dispatch
  api.py                  loopback JSON API + UI serving (token auth)
  cli.py                  serve / token / init / test entry points
  adapters/fake.py        scriptable fake executor (tests/enforcement)
  adapters/subprocess_executor.py   real gated executor, disposable workspace
  adapters/container_executor.py   Docker executor, disposable-copy mount (gated)
  adapters/hermes_ingest.py       read-only external ingest (path-allowlisted)
  discovery.py                    allowlisted, read-only tool discovery
  logging_setup.py                structured logging + secret redaction
  paths.py                        pure POSIX path-scope logic
  evidence.py                     shared test-signal detection (framework-first)
  web/index.html          single-file RTL dashboard (offline, no CDN)
tests/                    643 tests (A1–A13 + CLI gates)
tests/live_server.py      shared harness: OS-chosen port, identity-checked readiness
run_tests.py              file-writing test runner (sandbox-safe)
e2e_verify.py             11-step product verification over real HTTP
check_ui.py               UI structural validation (balance + handler wiring)
```

## Operations

See [RUNBOOK.md](RUNBOOK.md) for start/stop, token rotation, backup/recovery,
enabling the subprocess executor, and incident handling.

## License

MIT (pyproject.toml).
