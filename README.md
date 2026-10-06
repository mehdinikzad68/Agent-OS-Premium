# Agent OS / Mission Control

A personal, **local** control plane for AI agents: deterministic state,
human-only approvals, deny-before-dispatch enforcement, a durable audit trail
with evidence, and a built-in dashboard.

**The application lives in [`control-service/`](control-service/).**

## Documentation

| Document | Purpose |
|---|---|
| [docs/00-CURRENT-STATE.md](docs/00-CURRENT-STATE.md) | **Start here** — repository state today: branch, HEAD, uncommitted changes, which UI is authoritative |
| [docs/CAPABILITY-MATRIX.md](docs/CAPABILITY-MATRIX.md) | What is implemented vs. planned, with the evidence for each claim |
| [docs/01-installation-guide.md](docs/01-installation-guide.md) | System requirements, installation, first run |
| [docs/02-usage-guide.md](docs/02-usage-guide.md) | Daily operations: missions, jobs, approvals, evidence |
| [docs/03-api-documentation.md](docs/03-api-documentation.md) | Complete HTTP API reference |
| [docs/04-development-guide.md](docs/04-development-guide.md) | Architecture, testing, contributing |
| [docs/architecture/ADR-001-dashboard-rendering.md](docs/architecture/ADR-001-dashboard-rendering.md) | Canvas 2D is the official dashboard; Three.js is experimental |
| [docs/architecture/ADR-002-canonical-repository.md](docs/architecture/ADR-002-canonical-repository.md) | WSL Agent-OS is the only canonical repository |
| [control-service/READINESS.md](control-service/READINESS.md) | Honest limits — verified vs not implemented |
| [control-service/RUNBOOK.md](control-service/RUNBOOK.md) | Operations: start/stop, tokens, backup/recovery |
| [FINDINGS.md](FINDINGS.md) | Audit findings and resolutions |
| [docs/09-سند-طراحی-UI-2D-Mission-Control.md](docs/09-سند-طراحی-UI-2D-Mission-Control.md) | UI design specification (note: `docs/ui-2d-mission-control-design.md` is a byte-duplicate of this file) |
| [docs/10-گزارش-تست-امنیتی-و-نفوذ-Agent-OS.md](docs/10-گزارش-تست-امنیتی-و-نفوذ-Agent-OS.md) | Security & penetration test report |

> Also present but **historical/aspirational, not authoritative**:
> [docs/hermes-integration-layer.md](docs/hermes-integration-layer.md) (states
> "Nothing in this document is implemented"),
> [docs/phase6-design.md](docs/phase6-design.md), and the product
> roadmap/plan files (see [00-CURRENT-STATE](docs/00-CURRENT-STATE.md)).

## Quick start

```bash
# WSL / Linux — the tested platform (see READINESS.md). The canonical repo is
# /home/mehdi/workspace/Agent-OS (ADR-002). Do not develop in the Windows copy.
cd control-service
python3 -m agent_os.cli token
export AGENT_OS_TOKEN=<paste token>
python3 -m agent_os.cli serve --db mission-control.db
# open http://127.0.0.1:8470/ , paste the token, press اتصال
```

> The dashboard you get is the **Canvas 2D** UI, which is the official
> reference (ADR-001). A Three.js "Galaxy Command" variant exists in HEAD but
> is experimental and non-authoritative.

## Verify a build

```bash
cd control-service
python3 run_tests.py     # unittest suite -> .test-results.txt (exit 0 = pass)
python3 e2e_verify.py    # 11-step product verification over real HTTP
python3 check_ui.py      # UI structural validation
```

`unittest` is the canonical framework for this project. A static inventory of
the suite is **643 test functions across 43 files**; run the suite to get a
real pass/fail count. On a non-Linux host the POSIX/WSL-only test modules
**skip** honestly instead of erroring; WSL is the platform the suite is
verified on.

## Current status (honest)

Local, single-user, pre-integration, at `v0.2.0`. Verified: enforcement rules
A1–A13, durable evidence, restart durability, token auth, the full mission →
proposal → human approval → dispatch → evidence flow over HTTP, and a working
dashboard. **Not** done: any real agent runtime (Hermes/DSH/Antigravity),
an artifact store, OS-level worker containment, multi-user, network-egress
enforcement. See [READINESS.md](control-service/READINESS.md) and the
[Capability Matrix](docs/CAPABILITY-MATRIX.md).

Requires Python ≥ 3.11 on WSL/Linux (3.11 and 3.14 verified under WSL). No third-party dependencies.

## Architecture

```
UI (web/index.html) ─┐
CLI / scripts ───────┼─> HTTP API (token, loopback) ─> ControlService ─> SQLite
                     │         │                              │
                     │         └─ executor registry           └─ policy.py (pure, deny-first)
                     │                ├─ fake-executor  ← the ONLY default
                     │                ├─ subprocess-executor (opt-in: --enable-subprocess --source-workspace)
                     │                └─ container-executor (opt-in: --enable-container; python:3.14-slim)
```

> **Gating matters.** Only `fake-executor` is registered by default
> (`cli.py:66`). Every other executor requires explicit opt-in flags, and
> `subprocess-executor` additionally requires `--source-workspace`.

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
