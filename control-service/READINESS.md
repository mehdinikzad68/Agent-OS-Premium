# Agent OS — Readiness & Honest Limits (v0.2.0)

This document states exactly what is verified, what is not, and what must be
decided before this can be called integrated with real agent runtimes.

## 1. Verified working (evidence-backed)

| Capability | How it is verified | Result |
|---|---|---|
| Enforcement rules A1–A10 + CLI gates | `run_tests.py` (32 tests) | 32/32 pass on Python 3.14 **and** 3.11 |
| Full product flow over real HTTP | `e2e_verify.py`, 11 steps | PASS (see `e2e-result.txt`) |
| Token auth fail-closed, loopback bind | `tests/test_api.py` | pass |
| UI shell public / API protected | `tests/test_api.py::UiServingTest` | pass |
| Durable evidence in event log + `/api/jobs/{id}/evidence` | `test_evidence_*` + E2E step 11 | pass |
| Oversized request bodies refused (413) | `test_oversized_body_rejected` | pass |
| UI structural integrity + handler wiring | `check_ui.py` | pass |
| Durable state across restarts | A1 test + E2E step 10 | pass |
| Deny-before-dispatch (expired / destination / manifest / tools) | A2/A3 tests + E2E step 8 | pass |
| Idempotent dispatch + event dedup | A6 test + E2E step 7 | pass |
| Missing evidence never "verified" | A4 test + executor tests | pass |
| Lost worker = `interrupted_unknown`, no auto-rerun | A5 test | pass |
| Disposable workspace: source never modified; timeout ≠ success | `tests/test_subprocess_executor.py` | pass |
| Schema migration (v1→v2) | `MigrationTest` | pass |

Reproduce: `cd control-service && python run_tests.py && python e2e_verify.py && python check_ui.py`
(all must exit 0).

## 2. NOT implemented (deliberately, each needs a separate decision)

- **No real agent runtimes.** Hermes, DSH and Antigravity are not connected.
  The registry ships `fake-executor` (default) and a gated generic
  `subprocess-executor`. A DSH adapter is a future, separately approved piece.
- **No planner.** Nothing generates proposals automatically; jobs are created
  via API/UI. Hermes integration is unbuilt.
- **No artifact store.** Evidence is persisted in the append-only event log
  (bounded/truncated strings) and read back via `/api/jobs/{id}/evidence`; there
  is no content-addressed artifact repository with hashes/provenance (architecture
  §4 proposes it). Large worker output beyond the executor's capture limits is lost.
- **No Obsidian integration.** Revisioned knowledge docs exist in SQLite only.
- **UI is a functional dashboard, not the full spec.** Implemented: mission list/
  detail, job list, job detail panel with state-appropriate actions
  (request-approval / dispatch / reconcile), evidence viewer (test report + diff,
  read back from the event log), approval inbox with grant/deny, live event feed,
  status/capability panel, token connect. Missing: knowledge-editing UI, search,
  and rich diff rendering (evidence is shown as truncated plain text).
- **No OS-level containment enforcement.** The subprocess executor copies to a
  disposable dir and never edits the source, but it runs with the **same OS user
  privileges** as the server. It is *not* a security sandbox (architecture §6
  warning stands: worktree/copy/policy alone ≠ isolation boundary).
- **No multi-user, no roles, no remote access.** One bearer token, one human.
- **No network egress control.** The control plane makes no outbound calls; that
  is a property of the current code, not an enforced network policy.
- **No exactly-once external effects / no rollback.** A worker can act and crash
  before reporting; the system records `interrupted_unknown` and requires human
  reconciliation. Local patches are reviewable; sent messages/publications are not
  recoverable — therefore merge/publish is out of scope entirely.

## 3. Known technical limitations

- SQLite single-writer: all store access serialized by an in-process RLock.
  Fine for one local user; not for concurrent multi-process writers.
- `interrupted_unknown` is terminal for automation by design — it needs a human.
- Disposable sandboxes are deleted after each run unless `--keep-sandbox`; evidence
  beyond the captured stdout/stderr/exit-code summary is then gone.
- Test-signal detection is heuristic (`_detect_test_report`): a command that prints
  a passing-looking line can produce a "test report". Treat verified state as
  *"claimed and plausible"*, not proof — real adapters must supply structured
  reports.
- Windows is the tested platform (3.11 + 3.14). Linux/WSL untested.
- The UI requires the token and cannot itself perform approvals for you — that is
  intentional (human decision), but it means the dashboard is not "one-click".

## 4. Gates before real integration (each requires explicit approval)

1. Choose isolation for workers (Docker/WSL2 vs plain local) and containment tests.
2. Build + review a real DSH adapter (SDK vs ACP trade-offs already documented).
3. Decide Hermes planner interface and its restricted tool allowlist.
4. Define artifact storage (content hashes, provenance, redaction).
5. Re-run the full acceptance suite **after** each integration, not before.

Until those are done and re-verified, the honest status is:
**"local, single-user Mission Control with proven enforcement and a working
dashboard; not yet connected to any agent runtime."**
