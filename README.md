# Agent OS / Mission Control

A personal, **local** control plane for AI agents: deterministic state,
human-only approvals, deny-before-dispatch enforcement, a durable audit trail
with evidence, and a built-in dashboard.

**The application lives in [`control-service/`](control-service/).**

## Documentation

| Document | Purpose |
|---|---|
| [docs/01-installation-guide.md](docs/01-installation-guide.md) | System requirements, installation, first run |
| [docs/02-usage-guide.md](docs/02-usage-guide.md) | Daily operations: missions, jobs, approvals, evidence |
| [docs/03-api-documentation.md](docs/03-api-documentation.md) | Complete HTTP API reference |
| [docs/04-development-guide.md](docs/04-development-guide.md) | Architecture, testing, contributing |
| [control-service/READINESS.md](control-service/READINESS.md) | Honest limits — verified vs not implemented |
| [control-service/RUNBOOK.md](control-service/RUNBOOK.md) | Operations: start/stop, tokens, backup/recovery |
| [docs/09-سند-طراحی-UI-2D-Mission-Control.md](docs/09-سند-طراحی-UI-2D-Mission-Control.md) | UI design specification |
| [docs/10-گزارش-تست-امنیتی-و-نفوذ-Agent-OS.md](docs/10-گزارش-تست-امنیتی-و-نفوذ-Agent-OS.md) | Security & penetration test report |

## Quick start

```bash
# WSL / Linux — the tested platform (see READINESS.md)
cd control-service
python3 -m agent_os.cli token
export AGENT_OS_TOKEN=<paste token>
python3 -m agent_os.cli serve --db mission-control.db
# open http://127.0.0.1:8470/ , paste the token, press اتصال
```

## Verify a build

```bash
cd control-service
python3 run_tests.py     # 643 tests -> .test-results.txt (exit 0 = pass)
python3 e2e_verify.py    # 11-step product verification over real HTTP
python3 check_ui.py      # UI structural validation
```

On a non-Linux host the POSIX/WSL-only test modules **skip** honestly
instead of erroring; WSL is the platform the suite is verified on.

## Current status (honest)

Local, single-user, pre-integration. Verified: enforcement rules A1–A13,
durable evidence, restart durability, token auth, the full mission →
proposal → human approval → dispatch → evidence flow over HTTP, and a working
dashboard. **Not** done: any real agent runtime (Hermes/DSH/Antigravity),
an artifact store, OS-level worker containment, multi-user, network-egress
enforcement. See [READINESS.md](control-service/READINESS.md).

Requires Python ≥ 3.11 on WSL/Linux (3.11 and 3.14 verified under WSL). No third-party dependencies.

## Architecture

```
UI (web/index.html) ─┐
CLI / scripts ───────┼─> HTTP API (token, loopback) ─> ControlService ─> SQLite
                     │         │                              │
                     │         └─ executor registry           └─ policy.py (pure, deny-first)
                     │                ├─ fake-executor
                     │                └─ subprocess-executor (gated, disposable copy)
                     │                └─ container-executor (Docker isolation)
```

## Key guarantees

| # | Guarantee |
|---|---|
| A1 | Restart preserves missions/approvals/event history |
| A2 | Expired approval / unapproved destination / amended manifest refused **before** dispatch |
| A3 | Planner/worker can never self-approve; tool inventory fixed |
| A4 | Missing test evidence never becomes verified completion |
| A5 | Lost worker = `interrupted/unknown` until human reconcile; no auto-rerun |
| A6 | Duplicate dispatch / event replay = zero duplicate actions |
| A7 | Knowledge edit on stale revision raises conflict |
| A8 | Token auth fail-closed; loopback-only (**enforced** by serve()); UI shell public, API protected |
| A9 | Disposable workspace executor: never touches source, timeout = not success |
| A10 | Evidence durable in event log + served by API; oversized bodies refused (413) |
| A11 | Approval is **single-use**: spent atomically on first dispatch |
| A12 | Approval is **bound to one action**, not just a ceiling |
| A13 | A grant **survives a restart** and is still usable, then still single-use |

## License

MIT (pyproject.toml)
