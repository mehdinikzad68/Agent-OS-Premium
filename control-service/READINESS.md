# Agent OS — Readiness & Honest Limits (v0.2.0)

This document states exactly what is verified, what is not, and what must be
decided before this can be called integrated with real agent runtimes.

Last measured: 2026-10-02, WSL2 Ubuntu-26.04, Python 3.14.4. Every number
below was produced on that machine on that day. The tree is uncommitted at the
time of writing; the counts are measured, not asserted.

This revision covers Phase 5 (a real approval gate) and a test-harness defect
found while verifying it. The Phase 3 and Phase 4 rows are unchanged and were
not re-measured.

## 0. Phase status

| Phase | Focus | Status |
|---|---|---|
| 0 | Safe local baseline | complete — owner accepted |
| 1 | Bilingual i18n / RTL-LTR | complete — owner accepted |
| 2 | Project registry, read-only | complete — **owner accepted 2026-09-28** |
| 3 | Tool discovery + explicit registration | **code complete, owner gate not yet granted** |
| 4 | Honest event ingestion | code complete, PROVEN on the real profile; owner acceptance not yet granted |
| 5 | A real approval gate for one limited action | code complete and PROVEN; owner acceptance not yet granted |
| 6 | Per-project runner and constrained authority | **complete — container executor with Docker isolation; F2 CLOSED** |
| 7–10 | Everyday loop, Mission Control, personalisation, release | not started |

Phase 2's three exit criteria were measured on the running product, not read
off the code: a missing path, an out-of-scope path and a `../` escape are each
refused with HTTP 400; a registered project survives a restart; and the
registration path contains no `subprocess`, `Popen`, `docker`, `mount` or
`os.system` call.

## 1. Verified working (evidence-backed)

| Capability | How it is verified | Result |
|---|---|---|
| Enforcement rules A1–A13 + CLI gates | `python3 -B -m unittest discover -s tests -t .` | **643/643** pass on Python 3.14.4 (WSL) |
| Full product flow over real HTTP | `e2e_verify.py` | PASS |
| UI structural integrity + handler wiring | `check_ui.py` | pass |
| Token auth fail-closed; loopback bind **enforced** (serve() refuses other hosts) | `tests/test_api.py` + `tests/test_api_edge_cases.py` | pass |
| UI shell public / API protected | `tests/test_api.py::UiServingTest` | pass |
| Durable evidence in event log + `/api/jobs/{id}/evidence` | `test_evidence_*` + E2E | pass |
| Oversized request bodies refused (413) | `test_oversized_body_rejected` | pass |
| **A broken executor ends the job `FAILED`, never stuck `RUNNING`** | `test_executor_failure_recovery.py` (3 tests) | pass |
| Naive `expires_at` normalised; absent ids answer 404, not 500 | `test_api_edge_cases.py` | pass |
| **Loopback is enforced, not just documented** (`serve()` refuses other hosts; CLI exits 2) | `test_api_edge_cases.py` + `test_cli.py` | pass |
| **Ingest sources are allowlisted** (env + Hermes roots; `..`/symlink-proof) | `test_ingest_allowlist.py` (4) + `test_ingest_api.py` 403 | pass |
| **Evidence (executor stdout) is redacted on write and on read** | `test_evidence_redaction.py` (2 tests) | pass |
| Test-signal detection: one shared helper, framework summaries first | `test_evidence_detection.py` (6 tests) | pass |
| Durable state across restarts | A1 test + E2E | pass |
| Deny-before-dispatch (expired / destination / manifest / tools) | A2/A3 tests + E2E | pass |
| Idempotent dispatch + event dedup | A6 test + E2E | pass |
| **An approval is single-use; a spent approval can never authorise a second execution** | `test_phase5.py` + `p5_proof.py` (4 checks) — PROVEN, and `NOT PROVEN` with policy check 9 removed | pass |
| **An approval is bound to one action, not only a ceiling of actions** | `test_phase5.py` action-binding tests | pass |
| **A grant survives a restart and is still single-use afterwards** | `test_phase5.py::RestartDurabilityTest` (restart against the same database) | pass |
| **The dispatch path enforces the gate** — a job with no granted approval is refused before the executor runs | measured: `dispatch` raised `no_approval_record`, 0 executions | pass |
| **The startup banner states the gate is enforced and names what is still unbounded** | `test_command_validation.py::BypassIsDeclaredTest` | pass |
| Missing evidence never "verified" | A4 test + executor tests | pass |
| Lost worker = `interrupted_unknown`, no auto-rerun | A5 test | pass |
| Schema migration (v1 → current, v4) | `test_subprocess_executor.py::MigrationTest` | pass |
| **An approval names the exact command it authorised** | F1: `f1_proof.py` over real HTTP — PROVEN, and `NOT PROVEN` when the policy check is disabled | pass |
| **A timeout kills the whole process group, not just the child** | F3: `f3_proof.py` — PROVEN (marker unchanged, zero survivors) | pass |
| **An escaping symlink refuses the run before anything is copied** | F5: `f5_proof.py` — PROVEN, and `NOT PROVEN` with the guard removed (the secret returned in the evidence body) | pass |
| Structured logging + CLI viewer, console only when `AGENT_OS_DEBUG=1` | `logging_setup.py` + `logview.py` | pass |
| **Tool discovery installs nothing and writes no file** | F-phase3: `p3_proof.py` over real HTTP — 21 checks; a directory that is watched for new files stays empty | pass |
| **An unreadable tool version is reported `unknown`, never guessed** | 31 unit tests; the recogniser matched from the start of the line, so "loaded 3 plugins" cannot become version 3 | pass |
| **A discovered tool is not thereby permitted to run** | `grants_execution` is `False` on every row; the executor list is byte-identical before and after; the executor source never reads the tool table | pass |
| **Registration and removal are reviewable from the UI** | `check_ui.py` + 28 UI tests, 13/13 mutations killed, and **seen rendered by the owner (2026-09-28)**: the panel lists the seven real tools with versions, the `exact`/`wsl`/`windows_mount` badges, the dsh Windows-through-WSL note, and `grants no execution` beside the registered git | pass |

Reproduce (all must exit 0):

```bash
cd control-service
python3 -B -m unittest discover -s tests -t .   # 643 tests
python3 -B e2e_verify.py                        # 11 steps
python3 -B check_ui.py
python3 -B p5_proof.py                          # Phase 5: single-use, over real HTTP
python3 -B p5_mutation_check.py                 # ...and it goes red without the guard
```

### Findings closed since the last revision

Ten security findings were opened against this tree. All ten are closed.
Details and evidence in `../FINDINGS.md`.

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

### The test harness lied, and had done so since Phase 4

Four suites (`test_f11`, `test_phase5`, `test_tool_api`, `test_ingest_api`)
each booted a real server on a **hard-coded port** and treated any `200` on
`/api/status` as readiness. That probe cannot tell *whose* server answered.

When a run is killed mid-suite, its child server survives as an orphan and
keeps the port. The next run's own child then fails to bind, but the probe
still succeeds against the orphan - so the suite silently asserts against a
**stale database**. Observed: `added 0 != 3` / `skipped 3` in the ingest suite
(talking to a server from a previous run), and `Connection refused` in the tool
suite once the orphan was reaped. Neither reproduced in isolation.

This exact failure had already been diagnosed and written down in Phase 4 -
`FINDINGS.md` records "port collision on test harness caused false results" -
but the fix landed only in `p4_real_proof.py`. The four shared suites kept the
defect, which is why it resurfaced here.

The fix removes the class, not one instance:

- the port is chosen by the kernel (`--port 0`) and parsed from the banner the
  CLI prints **after** binding, so two suites cannot collide and an orphan
  cannot occupy the port we asked for;
- readiness is proven against our own child: `/api/status` must report the
  `db_path` we handed it, so a foreign server fails loudly instead of silently;
- the child runs in its own session and is killed by process group.

Verified by starting a **decoy server on the old fixed port 8893** and running
the full suite: 449/449 pass, no orphan left behind. There is deliberately no
"reap leftover servers" helper - a pattern matching the test server's command
line also matches an operator's real instance.

A second defect in the same area was self-inflicted and is recorded because it
was found by the end-to-end verifier, not by a unit test: an early Phase 5 edit
moved the consumed-approval check **ahead of** the documented A6 idempotency
check. That turned a replay of a finished job from `200 duplicated=true` into a
`409`, breaking `e2e_verify.py` step 7. The order was restored: A6 answers a
replay first, and single-use is enforced by the action running once
(`store.consume_approval` is atomic on first dispatch) plus policy check 9 -
not by turning a retry into an error.

## 2. NOT implemented (deliberately, each needs a separate decision)

- **The tool panel has never been seen rendered.** No browser on this host can
  reach the WSL server (a navigation attempt timed out at 420 s), so the panel
  was verified as markup, wiring and escaping - not as pixels. Three things are
  therefore unestablished: that it is *visible*, that the Persian text is
  *legible* in the panel, and that it is *discoverable* - it is the last
  element on a scrolling page, below the event feed, the diagnostics box and
  the project list. A fresh database also shows both lists empty, which on
  screen is indistinguishable from "the feature is missing". The owner
  reported not seeing it, which is the evidence that discoverability is not
  established. Treat the UI as written-but-unconfirmed.
- **Tool discovery exists but is not approved, and grants nothing.** Probing,
  the registry, and the UI panel are built and tested. What does not exist is
  the owner's acceptance, and — more importantly — any path from a registered
  tool to actually running it. `grants_execution` is `False` on every row and
  no executor consults the table, so a registered tool is a record, not a
  capability.
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
- **OS-level containment — CLOSED in Phase 6.** The container executor runs
  each command inside a Docker container with no network, read-only root,
  no capabilities, and only the project directory mounted. F2 is closed.
  The subprocess executor still runs with server privileges — it is gated
  behind `--enable-subprocess` and is not the default.
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
- **No concurrency test for single-use.** `consume_approval` is an atomic
  `UPDATE ... WHERE consumed_at IS NULL`, so a double spend cannot succeed, but
  no test fires two dispatches simultaneously. All store access is serialized
  by one in-process `RLock`, so a meaningful test needs a second process.
- **Approval expiry has no default TTL.** `request_approval(expires_at=None)`
  creates a grant that never expires; the caller must pass `expires_at`. The
  expiry *check* is enforced (`approval_expired`), the *default* is absent.
- `interrupted_unknown` is terminal for automation by design — it needs a human.
- Disposable sandboxes are deleted after each run unless `--keep-sandbox`.
  A delete that fails is now **recorded** (`failed_cleanups()`, plus a WARNING
  in the log) rather than swallowed, but the directory still survives on disk.
- `keep_workspace=True` has no retention ceiling. Nothing bounds how many
  sandboxes can accumulate; this is a known gap, deliberately not filled in
  with an invented policy.
- `Project.read_only` is shown as a UI badge but is **not enforced**
  anywhere: declared-True, never consulted by an executor. The badge is
  a statement about intent, not a boundary (B3, review 2026-10-05).
- Test-signal detection is heuristic (`agent_os/evidence.py`:
  `detect_test_report` - one helper shared by both executors since B2): a
  command that
  prints a passing-looking line can produce a "test report". Treat verified
  state as *"claimed and plausible"*, not proof — real adapters must supply
  structured reports.
- A preserved symlink inside the sandbox still points at the original path. It
  is safe only because the copy guard has already refused everything escaping;
  a link reaching the sandbox therefore necessarily points inward.
- Linux/WSL is the tested platform. Windows is **not** verified: no test run on
  native Windows is recorded, so treat any Windows-specific path (drive letters,
  separators, process spawning) as unproven. The earlier claim of "Windows
  tested, 3.11 + 3.14" was false on both counts. On a non-Linux host the suite
  now **skips** its POSIX/WSL-only modules at import (T2 guard, review
  2026-10-05) instead of erroring on them; the portable subset still has no
  recorded Windows run.
- The UI requires the token and cannot itself perform approvals — intentional
  (a human decides), but it means the dashboard is not "one-click".
- **A discovery probe runs with the server's privileges.** A binary that writes
  a file when asked for its version will do so; nothing in discovery can
  prevent that by inspection, which is why the allowlist in
  `agent_os/discovery.py` is the entire safety boundary for probing. This is
  the same exposure as F2, at a smaller blast radius.
- **Only the `wsl` environment is supported.** Asking about `windows` is
  refused with a reason rather than returning an empty list, because an empty
  list reads as "nothing is installed" — a different and false claim.
- **`dsh` currently resolves to a Windows install** reached through WSL interop
  (`/mnt/c/Users/Mehdi/.../node/dsh`, reporting 0.1.5-rc.2). It runs, so it is
  not refused, but it is labelled `provenance=windows_mount` everywhere. The
  native WSL install is not on PATH by name.

## 4. Gates before real integration (each requires explicit approval)

0. **Phase 3 acceptance** — the three exit criteria are measured and met
   (discovery writes nothing; `unknown` is reported rather than guessed;
   register and remove are reviewable from the UI).

0b. **Phase 4 and Phase 5 acceptance** — both are code complete and PROVEN
   (`p4_real_proof.py` on the real Hermes profile; `p5_proof.py` over real
   HTTP, with its mutation check). What is outstanding is the owner's
   acceptance, which is a human decision, not a measurement.

   The UI row is now `pass` rather than `partial`: the owner opened the page and
   the panel rendered. Three items came out of that session and are recorded in
   the appendix - F11 and two UI defects - all deferred by owner decision, none
   of them an exit criterion. What is still outstanding is the owner's
   acceptance, which is a human decision.
1. **Containment for workers** (F2 / Phase 6): **CLOSED** — container executor
   with Docker isolation, proven by `test_container_boundary.py` and `p6_proof.py`.
2. **A real DSH adapter** — SDK vs ACP trade-offs already documented.
3. **The Hermes planner interface** and its restricted tool allowlist.
4. **Artifact storage** — content hashes, provenance, redaction.
5. **Re-run the full acceptance suite after each integration, not before.**

Until those are done and re-verified, the honest status is:

**"Local, single-user Mission Control with proven enforcement and a working
dashboard. Ten security findings closed. Tool discovery and a reviewable
registry exist and grant no execution rights. The approval gate is real and
enforced on the dispatch path: a job without a granted, unconsumed,
action-bound approval is refused before the executor runs, and a spent
approval can never authorise a second execution. The container executor
provides real OS-level isolation (Docker with no network, read-only root,
no capabilities). Not yet connected to any agent runtime."**

## Open items deferred after the owner saw the UI work

Found by following the owner's own report, not by test coverage. None is a
Phase 3 exit criterion; all are recorded so they are not lost.

All three are now **closed** (owner-authorised 2026-09-28) - see below.

| item | what | status |
|---|---|---|
| F11 | a missing resource answers 500 instead of 404 | CLOSED - `f11_proof.py` 15/15, all mutants red |
| - | `runDiscovery()` issues an unauthenticated request when no token is set | CLOSED - token guard + a message in both languages |
| - | Diagnostics captures `status` then never renders it | CLOSED - the render now names the status and the request |

The F11 cause was an `IndexError` on a missing path segment, not a `None`
reaching a serialiser: the `KeyError` guard already existed and was already
caught. The same function also wrote a `mission_activated` event for a mission
that did not exist, before asserting; the check now precedes every write.

**Not reproduced, recorded as unconfirmed:** the five "response body was not
JSON" warnings the owner saw. Every path of the 4-second loop returned valid
JSON across eight rounds, six concurrent requests, and every 401/404 path, and
the server is a ThreadingHTTPServer. The leading explanation is the no-token
session, but it was not confirmed.

**Method note:** two conclusions in this phase were wrong and were corrected by
measurement - a screenshot read as showing a different machine, and a missing
token read as a broken panel. Both came from acting on weak evidence before
measuring.

---

## Appendix — two Phase 3 findings that changed the design

Both were measured before any code was written, and in both cases the first
design guess was wrong.

**A Windows install reached through WSL does run.** The plan was to refuse any
tool resolving under `/mnt/<drive>/`, on the grounds that a WSL project cannot
use a Windows binary. Measuring `dsh` showed it executing with `rc=0` through
WSL interop. That rule would have discarded a working tool. The rule became:
decide exec-ability by probing, refuse only what demonstrably cannot run, and
report `provenance` next to the version so a Windows version is not read as a
POSIX one.

**The same tool name can be two installs.** `dsh` exists once on PATH and it is
the Windows one; the native WSL install is not reachable by name. So the
registry key is `(environment, name, path)`, not `name` — otherwise "dsh" is one
row that is half true.

And one found by the anti-proof rather than by a test: `api.py` was forcing
`grants_execution` to `False` in the response, which made the model's field dead
code and created two sources of truth. Every behavioural test stayed green
while the override was reintroduced, because the override wrote the value the
tests already expected. The invariant is now stated structurally in
`test_tool_api.py`, which does catch it.
