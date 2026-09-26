# Agent OS / Mission Control

A personal, **local** control plane for AI agents: deterministic state,
human-only approvals, deny-before-dispatch enforcement, a durable audit trail
with evidence, and a built-in dashboard.

**The application lives in [`control-service/`](control-service/).**

| Document | Purpose |
|---|---|
| [`control-service/README.md`](control-service/README.md) | What it is, how to run it, what is enforced |
| [`control-service/READINESS.md`](control-service/READINESS.md) | **Honest limits** — verified vs not implemented, integration gates |
| [`control-service/RUNBOOK.md`](control-service/RUNBOOK.md) | Operations: start/stop, tokens, backup/recovery, incidents |
| [`AGENT-OS-HANDOFF.md`](AGENT-OS-HANDOFF.md) | Original project handoff (project intent, runtime facts, decisions) |
| [`outputs/`](outputs/) | Architecture brief, Phase-0 assessment, verification results |
| [`.agent-ai/memory/`](.agent-ai/memory/) | Durable project memory across sessions |

## Quick start

```bat
cd control-service
"C:\Users\Mehdi\AppData\Local\Programs\Python\Python314\python.exe" -m agent_os.cli token
set AGENT_OS_TOKEN=<paste token>
"C:\Users\Mehdi\AppData\Local\Programs\Python\Python314\python.exe" -m agent_os.cli serve --db mission-control.db
:: open http://127.0.0.1:8470/ , paste the token, press اتصال
```

## Verify a build

```bat
cd control-service
python run_tests.py     :: 32 enforcement/security + CLI tests
python e2e_verify.py    :: 11-step product verification over real HTTP
python check_ui.py      :: UI structural validation
```

## Current status (honest)

Local, single-user, pre-integration. Verified: enforcement rules A1–A10,
durable evidence, restart durability, token auth, the full mission →
proposal → human approval → dispatch → evidence flow over HTTP, and a working
dashboard. **Not** done: any real agent runtime (Hermes/DSH/Antigravity), an
artifact store, OS-level worker containment, multi-user, network-egress
enforcement. See [READINESS.md](control-service/READINESS.md).

Requires Python ≥ 3.11 (3.11 and 3.14 verified). No third-party dependencies.