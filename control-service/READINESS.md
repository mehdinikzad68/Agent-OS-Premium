# Agent OS — Readiness & Honest Limits (v0.2.0)

This document states exactly what is verified, what is not, and what must be
decided before this can be called integrated with real agent runtimes.

Last measured: 2026-09-28, WSL2 Ubuntu-26.04, Python 3.14.4, at commit
`b954982`. Every number below was produced on that machine on that day.

## 0. Phase status

| Phase | Focus | Status |
|---|---|---|
| 0 | Safe local baseline | complete — owner accepted |
| 1 | Bilingual i18n / RTL-LTR | complete — owner accepted |
| 2 | Project registry, read-only | complete — **owner accepted 2026-09-28** |
| 3 | Tool discovery + explicit registration | **not started; no code exists** |
| 4 | Honest event ingestion | event store exists; the operational timeline is not built |
| 5 | A real approval gate for one limited action | approval + policy exist; the gate is not yet a full product surface |
| 6 | Per-project runner and constrained authority | not started — this is where F2 belongs |
| 7–10 | Everyday loop, Mission Control, personalisation, release | not started |

Phase 2's three exit criteria were measured on the running product, not read
off the code: a missing path, an out-of-scope path and a `../` escape are each
refused with HTTP 400; a registered project survives a restart; and the
registration path contains no `subprocess`, `Popen`, `docker`, `mount` or
`os.system` call.

## 1. Verified working (evidence-backed)

| Capability | How it is verified | Result |
|---|---|---|
| Enforcement rules A1–A10 + CLI gates | `python3 -B -m unittest discover -s tests -t .` | **295/295** pass on Python 3.14.4 |
| Full product flow over real HTTP | `e2e_verify.py` | PASS |
| UI structural integrity + handler wiring | `check_ui.py` | pass |
| Token auth fail-closed, loopback bind | `tests/test_api.py` | pass |
| UI shell public / API protected | `tests/test_api.py::UiServingTest` | pass |
| Durable evidence in event log + `/api/jobs/{id}/evidence` | `test_evidence_*` + E2E | pass |
| Oversized request bodies refused (413) | `test_oversized_body_rejected` | pass |
| Durable state across restarts | A1 test + E2E | pass |
| Deny-before-dispatch (expired / destination / manifest / tools) | A2/A3 tests + E2E | pass |
| Idempotent dispatch + event dedup | A6 test + E2E | pass |
| Missing evidence never "verified" | A4 test + executor tests | pass |
| Lost worker = `interrupted_unknown`, no auto-rerun | A5 test | pass |
| Schema migration (v1→v2) | `MigrationTest` | pass |
| **An approval names the exact command it authorised** | F1: `f1_proof.py` over real HTTP — PROVEN, and `NOT PROVEN` when the policy check is disabled | pass |
| **A timeout kills the whole process group, not just the child** | F3: `f3_proof.py` — PROVEN (marker unchanged, zero survivors) | pass |
| **An escaping symlink refuses the run before anything is copied** | F5: `f5_proof.py` — PROVEN, and `NOT PROVEN` with the guard removed (the secret returned in the evidence body) | pass |
| Structured logging + CLI viewer, console only when `AGENT_OS_DEBUG=1` | `logging_setup.py` + `logview.py` | pass |

Reproduce (all must exit 0):

```bash
cd control-service
python3 -B -m unittest discover -s tests -t .   # 295 tests
python3 -B e2e_verify.py
python3 -B check_ui.py
```

### Findings closed since the last revision

Ten security findings were opened against this tree. Nine are closed; one is
deliberately partial. Details and evidence in `../FINDINGS.md`.

- **F1** blind approval — the UI now shows the exact command being authorised,
  and a grant whose stored command no longer matches the job is refused.
- **F3** a timeout killed only the direct child, so a backgrounded grandchild
  survived. The process group is now killed with `SIGKILL` on every exit path.
- **F5** the workspace copy followed symlinks, so outside content entered the
  sandbox *and was returned over HTTP by the evidence endpoint*. An escaping
  link now refuses the run before the sandbox is created.
- **F6** five silent `rmtree(ignore_errors=True)` call sites; every cleanup
  failure is now logged and recorded with the path that caused it.
- **F7** two resource leaks (a sqlite handle on a failed startup, a socket
  bound before the caller's `try`); both are closed on any failure, including
  `Ctrl-C`.
- **F8** `jobs.command` could not survive storage at all; it is canonical JSON
  and the executor decodes it fail-closed.
- **F9/F10** the copy recursed through a link to an ancestor until `ELOOP`
  (links are now copied as links), and an unreachable `scope` parameter was
  removed rather than wired up.
- **F4** a type annotation that was documentation rather than a guard.

The recurring shape: every one of these sat on a path no test exercised. A
green suite was reporting what it covered, not breadth. Each fix shipped with
a mutation run and, where the claim was behavioural, an HTTP proof that goes
red when the fix is disabled.

## 2. NOT implemented (deliberately, each needs a separate decision)

- **No tool discovery or tool registry.** Phase 3 has no code. Nothing is
  probed, nothing is registered, and the UI has no tool surface. A tool that is
  found is not thereby allowed to run.
- **No real agent runtimes.** Hermes, DSH and Antigravity are not connected.
  The registry ships `fake-executor` (default) and a gated generic
  `subprocess-executor`, which requires both `--enable-subprocess` and
  `--source-workspace`. A DSH adapter is a future, separately approved piece.
- **No planner.** Nothing generates proposals automatically; jobs are created
  via API/UI. Hermes integration is unbuilt.
- **No artifact store.** Evidence is persisted in the append-only event log
  (bounded/truncated strings) and read back via `/api/jobs/{id}/evidence`; there
  is no content-addressed artifact repository with hashes/provenance. Worker
  output beyond the executor's capture limits is lost.
- **No Obsidian integration.** Revisioned knowledge docs exist in SQLite only.
- **UI is a functional dashboard, not the full spec.** Implemented: mission
  list/detail, job list, job detail with state-appropriate actions, evidence
  viewer, approval inbox with grant/deny, live event feed, status panel, token
  connect. Missing: knowledge-editing UI, search, rich diff rendering, and any
  tool-management surface.
- **No OS-level containment enforcement — F2, deferred to Phase 6.** The
  executor copies the workspace to a disposable directory, refuses symlinks
  that leave it, and never edits the source. But the child runs with the **same
  OS user privileges as the server**: it can read any path the server can read,
  and write outside the sandbox. F5 closed the *copy*, not the *read*. Worktree
  plus copy plus policy is not an isolation boundary.
- **No multi-user, no roles, no remote access.** One bearer token, one human.
- **No network egress control.** The control plane makes no outbound calls;
  that is a property of the current code, not an enforced network policy.
- **No exactly-once external effects / no rollback.** A worker can act and crash
  before reporting; the system records `interrupted_unknown` and requires human
  reconciliation. Local patches are reviewable; sent messages and publications
  are not recoverable — so merge/publish is out of scope entirely.

## 3. Known technical limitations

- SQLite single-writer: all store access is serialized by an in-process
  `RLock`. Fine for one local user; not for concurrent multi-process writers.
- `interrupted_unknown` is terminal for automation by design — it needs a human.
- Disposable sandboxes are deleted after each run unless `--keep-sandbox`.
  A delete that fails is now **recorded** (`failed_cleanups()`, plus a WARNING
  in the log) rather than swallowed, but the directory still survives on disk.
- `keep_workspace=True` has no retention ceiling. Nothing bounds how many
  sandboxes can accumulate; this is a known gap, deliberately not filled in
  with an invented policy.
- Test-signal detection is heuristic (`_detect_test_report`): a command that
  prints a passing-looking line can produce a "test report". Treat verified
  state as *"claimed and plausible"*, not proof — real adapters must supply
  structured reports.
- A preserved symlink inside the sandbox still points at the original path. It
  is safe only because the copy guard has already refused everything escaping;
  a link reaching the sandbox therefore necessarily points inward.
- Linux/WSL is the tested platform. Windows is **not** verified: no test run on
  native Windows is recorded, so treat any Windows-specific path (drive letters,
  separators, process spawning) as unproven. The earlier claim of "Windows
  tested, 3.11 + 3.14" was false on both counts.
- The UI requires the token and cannot itself perform approvals — intentional
  (a human decides), but it means the dashboard is not "one-click".

## 4. Gates before real integration (each requires explicit approval)

1. **Containment for workers** (F2 / Phase 6): decide the isolation model and
   write the negative tests that prove it. This is the only gate that blocks
   the product's central security claim.
2. **A real DSH adapter** — SDK vs ACP trade-offs already documented.
3. **The Hermes planner interface** and its restricted tool allowlist.
4. **Artifact storage** — content hashes, provenance, redaction.
5. **Re-run the full acceptance suite after each integration, not before.**

Until those are done and re-verified, the honest status is:

**"Local, single-user Mission Control with proven enforcement and a working
dashboard. Nine security findings closed, one deliberately partial. Not yet
connected to any agent runtime, and not yet isolated from the machine it runs
on."**
