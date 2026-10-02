# FINDINGS — Independent review register

This file lives in the repository on purpose. The first review register did
not, and the cost was concrete: a later session could not find the findings, did
not know they existed, described the project status without them, and the owner
had to ask what happened to the other six.

Verified: the `F1`–`F8` register was discussed in a session, and the only
surviving copy was in a vault note outside the repo. Nothing in the working
tree mentioned F1, F2 or F8. Keep this file in the repo and the next reader has
the list.

**Source of the findings:** cold independent review of `99a345b` (the whole
repository at the end of Phase 2), run with `agy` in `--mode plan`
(read-only), two models, every claim adjudicated against the code and git
history. Four claims from the reviewers were rejected as wrong. The method
matters as much as the list: a reviewer's report is a hypothesis, not a finding.

**Status vocabulary**

- `OPEN` — reproducible, not fixed
- `CLOSED` — fixed, with the commit named
- `PARTIAL` — mitigated, with the real limit stated
- `DEFERRED` — deliberately postponed to a named phase

---

## Current state

| | Finding | Severity | Status |
|---|---|---|---|
| F1 | An approval did not name the command it authorized | critical (conditional) | **CLOSED** — `e2aed6e`; proof repaired `a9e111e` |
| F2 | `cwd` is a starting point, not a boundary; writes outside are not prevented | high | **PARTIAL** — declared in `cddcb46`, real boundary is Phase 6 |
| F3 | `kill()` does not kill the process group; a backgrounded child survives the timeout | medium | **CLOSED** — process group + SIGKILL on every exit path |
| F4 | The `command` type annotation was neither a guard nor correct | medium | **CLOSED** — `cddcb46` (edge validation) + `6079c22` (storage) |
| F5 | `copytree` follows symlinks, so outside content was copied in and returned by the evidence endpoint | high | **CLOSED** — refuse escaping links before the copy |
| F6 | Cleanup failures are silent (`ignore_errors=True`, five sites) | low | **CLOSED** — every failure is recorded and retrievable |
| F7 | Two resource leaks: sqlite connect, and a window before `try/finally` | low | **CLOSED** — both closed on any failure, including Ctrl-C |
| F8 | `jobs.command` could not survive storage at all | — | **CLOSED** — `6079c22` |
| F9 | `_copytree_into` recurses through a link to an ancestor until ELOOP; fails closed but with a raw OSError | low | **CLOSED** — links are copied as links, never followed |
| F10 | `POST /api/projects` ignores the `scope` parameter its service method accepts | informational | **CLOSED** — the parameter is removed, not wired up |

`SCHEMA_VERSION` is 2 and must stay 2 for the work above; F1 and F8 both needed
no migration because `scope_json` and `command` are existing columns.

---

## F1 — an approval did not name the command it authorized — CLOSED

Measured before the fix, the approval the human reads:

```
scope = {'executor': 'subprocess-executor',
         'workspace_paths': ['/w'],
         'actions': ['run_tests']}
job.command = '["python","-c","import shutil; shutil.rmtree(...)"]'
```

Approving meant approving "run tests in /w" while the effect was whatever argv
the job carried. The UI card showed only the executor and the actions.

**The original report was wrong about the mechanism.** It said the dispatch
path never checks the approval record. It does: `policy.validate_dispatch`
returns `no_approval_record` without one, and `manifest_hash` is captured from
the job at approval time and re-checked at dispatch, so changing the command
already invalidated the grant.

So this was never an exploitable bypass. What it was: a **decision made
blind**, and a **structure that depended on a single hash function**. The fix
puts `command` in `ApprovalScope` and compares it explicitly, so the hash is a
second line rather than the only one. The UI now renders the argv.

The durable rule, which is the part worth keeping: **any field a caller can set
is a field that can lie.** Bounds (`executor`, `workspace_paths`, `actions`) are
ceilings a caller may propose and a human may refuse. The payload (`command`)
is the operation and is never caller-set — enforced in the service, not only at
the API edge, because a direct service caller can reach it too.

### The fix shipped, but its proof could not fail (`a9e111e`)

The first version of `f1_proof.py` was green for a full phase and was not
evidence. Every step in it dispatched an **honestly approved** job, so

```python
if approval.scope.command != job.command:
```

was never `False` in any scenario the proof built. Measured: replacing only
that line with `if False:` still printed `PROVEN`. The proof exercised the
feature's happy path and never the branch the finding is about.

Proof step 4 now covers the gap — a job is approved and granted, then the
**stored** `scope_json` is rewritten to name a different command, the row a
confused writer or a pre-fix insert would leave. The job is untouched, so
`manifest_hash` still matches and the refusal can only be the command check:

| | dispatch result |
|---|---|
| real code | `409 command_not_in_scope` |
| command check disabled | `200 completed_verified` — the tampered command ran |

Refusing *for the named reason* is the evidence. Asserting only `status >= 400`
would also have passed on the manifest check, which is a different guarantee.

**The generalisable lesson, and the reason this is in the register rather than
only in the commit:** enumerate the states a proof exercises and ask which one
makes the guarded branch false. A proof assembled from happy paths can be
proof of a feature that is absent.

## F2 — `cwd` is not a boundary — PARTIAL, deferred to Phase 6

`shell=False` is correct and blocks shell injection. But `cwd` sets the
starting directory, not a limit: `["touch", "/tmp/x"]` succeeds, and so does a
script that writes to `~`.

What is done: the word "sandbox" is now accompanied by an explicit statement
that it is a working copy and not a security boundary, in the startup banner
and in a structured `executor.bypass_declared` event at WARNING level.

What is not done, and cannot be: real containment. That is Phase 6 — a
per-project runner with a minimal mount set. Until then, treat any subprocess
dispatch as running with the server's own OS privileges. **Do not read the
remaining risk as closed.**

## F3 — the timeout kills only the direct child — CLOSED

`proc.kill()` kills the immediate child. `["bash", "-c", "sleep 999 &"]` leaves
a grandchild running while the timeout is reported honestly as a timeout.

Same root cause produces a second leak: there is no `finally` around the
`Popen`, so a `KeyboardInterrupt` during `wait()` abandons the process.

Fix shape: start the child in its own session (`start_new_session=True`) and
signal the group, plus a `finally` that guarantees cleanup.

### Measured, then closed

Before the fix, with a job whose command spawns a background child:

| | |
|---|---|
| marker 1.5s after the timeout | 58 → **82** (still writing) |
| processes still running | **1** |
| timeout reporting | honest — `reason: timeout` |

The outcome was never a lie. The defect was that the tree kept running while
the API reported the work finished and the sandbox removed.

After: marker 58 → 58, zero survivors, timeout still reported honestly.

`start_new_session=True`, then `os.killpg` with SIGKILL, with the pid captured
the moment the child exists so a post-fork raise can still clean up.

**Two cleanup paths, and they are complementary — measured, not assumed:**

| configuration | grandchild survives |
|---|---|
| real code | no |
| `finally` removed | no |
| `except Exception` cleanup removed | no |
| **both removed** | **yes, 2 processes** |

So the `finally` is not redundant: `KeyboardInterrupt` is a `BaseException` and
`except Exception` never sees it.

**A test witness can be wrong even when the test is green.** The interrupt test
originally watched the marker's motion and passed with the `finally` neutered.
Instrumenting the call showed cleanup arriving from line 176, not the branch
under test: a frozen marker cannot distinguish "killed by the executor" from
"killed by the harness on the way out". Asserting on live pids fixed it.

**A SIGKILL→SIGTERM mutation that survived was a BAD mutation, not a weak
test** — the stamping child does not handle SIGTERM, so the two signals are
equivalent for it. The discriminating workload is a child that *ignores*
SIGTERM; that test now kills it and the mutation dies.

**Two of my own patches landed as comments only.** Twice, an edit anchored on
`shell=False,` moved the real line while leaving its comment behind, so
`start_new_session=True` existed in the file but only inside a docstring. The
mechanism tests caught it; a green suite over code that does not contain the
fix would not have.

**A finding narrowed by measurement rather than by argument.** A mutation
prompted the claim that cleanup depends on Popen *returning* — so a Popen
raising after the fork leaks. Measured: a Popen that raises reaps its own
child and leaks nothing. The uncovered case is the synthetic one where the pid
never reaches `run()`, which is not a defect to patch but a property to state.

Platform (owner decision): POSIX only, with an explicit refusal when
`os.killpg` is absent — no Windows branch, because the suite runs in WSL and
such a branch could never be exercised by any test here.

Two honest surfaces had to change with it: the startup banner claimed a timeout
"kills only the direct child, not its grandchildren", and the executor's bypass
event carried `timeout_kills_process_group=False`. Both now state what is true.
`writes_bounded=False` is unchanged — that is F2, still open.

## F4 — the type annotation was documentation, not a guard — CLOSED

`models.py` annotated `command: Optional[str]` while the only shape that works
is a list; and the API accepted any JSON type, so an `int` or `dict` reached
`Popen` and produced a 500 instead of a clean refusal.

Closed by two commits: `cddcb46` validates the shape at the HTTP edge with
permanent tests, and `6079c22` makes the stored form canonical JSON so it can
survive sqlite at all. The annotation is now true rather than aspirational.

## F5 — `copytree` follows symlinks — CLOSED

`shutil.copytree` defaults to `symlinks=False`, so a symlink is followed and the
target's **contents are copied**. A project containing `ln -s ~/.ssh link`
copies the keys into a directory the job can read and whose output can be
reported. Not an escape — a copy and a disclosure.

## F6 — cleanup failures are silent — CLOSED

### Measured

Five `rmtree(..., ignore_errors=True)` sites, not four — the register was one
short. Measured on a directory whose parent is read-only:

    rmtree(ignore_errors=True) raised nothing: True
    the dir survived: True

and nothing anywhere bounds the sandbox root, so `keep_workspace=True`
accumulates without a ceiling.

### Fixed

`_discard_sandbox(sandbox, why)` replaces all five. It logs at WARNING, appends
to a module-level `cleanup_failures` list (capped, oldest dropped first), and
returns whether the delete worked. `failed_cleanups()` hands out a copy so a
caller cannot erase the record; `clear_failed_cleanups()` is for tests.

Each site passes a distinct reason — `copy-failed`, `no-process-group-support`,
`timeout`, `executor-error`, `completed` — because "which path failed" is the
entire content of the record, and a copy-paste that reused one label would hide
exactly that. A test asserts each label is used exactly once.

A run whose cleanup failed still returns its result: a leftover directory is
not a reason to fail a run whose outcome is already known. The failure is
visible afterwards, which is the point.

### Evidence, and what the first attempt got wrong

The first version of the tests covered only the happy path. Mutation checking
reported 7 survivors, and measuring them first — the F5 lesson — showed this
time they were REAL gaps, not junk mutations: the timeout, executor-error,
fail-closed and copy-failed paths had no test at all. So every path is now
driven, and the mutation run is 13/13.

Two defects in my own tests along the way, both invisible to a green suite:
`addCleanup` runs AFTER `tearDown`, so the patched `rmtree` was still active
during cleanup; and a cap test that sliced the list by hand never exercised the
cap line it claimed to test.

The `keep_workspace` ceiling was deliberately NOT added. It is a real gap, but
it is a policy decision about disk usage, not a defect, and F6 as written was
about failures being invisible. Recorded here rather than silently folded in.

## F7 — two resource leaks — CLOSED

### Measured, both of them really happen

store.py, with `_init_schema` forced to fail:

    open fds on the db dir before: 0, after: 1
    LEAK: True

The caller has no handle to close it with, because `__init__` never returned.

api.py, the socket: `ThreadingHTTPServer` binds inside its own constructor, so
from that line the port is held. Measured directly: with the server object left
open after a post-bind failure the port stays held; with `server_close()` on
the failure path a probe socket binds and listens. So a port probe IS a valid
witness — which is what made the first version of the test checkable.

### Fixed

Both use `except BaseException`, not `except Exception`. A Ctrl-C during startup
is the realistic case, and `KeyboardInterrupt` is not an `Exception` — the same
reasoning F3's `finally` block exists. In store.py the close-on-failure is
itself wrapped, so a close that raises cannot mask the original startup error.

### Evidence, and a witness that measured the wrong thing

12 tests, mutation 8/8.

The socket test passed for a week of my own edits because it was broken in a
subtle way: it closed the fake servers and THEN probed the port, so it was
measuring its own cleanup rather than the code's. Running the mutation by hand
showed `server_close()` had been called zero times while the test still passed.
The port is now probed before any cleanup, and the call is asserted directly.

A second, sharper lesson: raising inside the fake's `__init__` escapes BEFORE
`serve()`'s `try` — a different path from the one the finding is about, and it
failed on healthy code. The post-bind assignment has to be what raises, which
is what a descriptor on the subclass does.

---

## The pattern behind F1, F3, F5 and F7

All four sat on a path no test touched. The suite was not weak; it was
reporting exactly what it covered, and coverage is not breadth.

**A green suite is not evidence of correctness.** The productive question is
which branch is untested — and the cheap way to find it is to look for the
documented-but-unexercised path: a parameter default, an error branch, a value
a caller always supplies explicitly.

## Phase gates

The roadmap rule is one topic per phase, and no phase starts before the previous
one's exit criteria are met **and the owner has accepted them**. Acceptance is a
human decision and is recorded here so the next session does not re-ask.

### Phase 2 — Project Registry — ACCEPTED 2026-09-28 by the owner

Measured on the running product before acceptance, not read off the code:

| Exit criterion | Result |
|---|---|
| a missing path is refused | HTTP 400 |
| a path outside the configured scope is refused | HTTP 400 |
| a `../` escape is refused | HTTP 400 |
| a registered project survives a restart | 1 project before and after |
| registration causes no mount and no command execution | no `subprocess` / `Popen` / `docker` / `mount` / `os.system` on that path |

### Phase 3 — Tool discovery and registry — code complete, AWAITING OWNER ACCEPTANCE

The three exit criteria, measured on the running product:

| Exit criterion | Result |
|---|---|
| discovery installs nothing and writes no file | a watched directory is empty after a real HTTP discovery run |
| an unknown path or non-standard output yields `unknown` | "loaded 3 plugins" cannot become version 3; the recogniser matches from the start of the line |
| registering **and removing** a tool, reviewable from the UI | both buttons present, both wired, 28 UI tests, 13/13 mutations killed — **structure only, never rendered** |

The constraint the roadmap states — a discovered tool is not thereby allowed to
run — is enforced in three independent places, because one assertion is easy to
satisfy by accident:

1. `grants_execution` is `False` on every registry row;
2. the executor list is byte-identical before and after discovery and
   registration;
3. the executor source contains no reference to the tool table at all.

Point 3 is what makes the phase safe to ship ahead of Phase 6. A behavioural
test only proves the calls it makes; reading the source proves there is nothing
for a later change to reach.

**What is NOT claimed:** nothing in the registry can be executed. A registered
tool is a record the owner made, not a capability.

**And what is claimed too strongly:** "reviewable from the UI". The panel was
verified as markup, wiring and escaping. It was never rendered — no browser on
this host reaches the WSL server. So visibility, Persian legibility and
discoverability are all unestablished, and the panel being the last element on
a scrolling page is a real gap, not a neutral detail. The owner's report that
they could not see it is the evidence.

With Phase 2 accepted, Phase 3 (Tool discovery and explicit registration) was
unblocked. Its own exit criteria, from the roadmap:

1. discovery that installs nothing and writes no file
2. an unknown path or non-standard output yields status `unknown`, not a guess
3. registering **and removing** a tool, reviewable from the UI

and the constraint stated by the roadmap itself: a discovered tool is not
thereby allowed to run.

### Phase 4 — Event Ingestion and Operational Timeline — code complete, PROVEN on real profile, AWAITING OWNER ACCEPTANCE

The exit criteria from the roadmap, measured against the owner's real, live Hermes profile (`state.db` on Windows drive via `/mnt/c`):

| Exit criterion | Result | Evidence |
|---|---|---|
| Traceable, correlated events from a real runtime | ✅ PROVEN | Real Hermes `state.db` ingested over HTTP (`POST /api/events/ingest`), carrying source (`desktop`), session IDs, tool names, call IDs, timestamps |
| Cursor advances reliably and replay is safe (dedup) | ✅ PROVEN | Replay adds 0 rows (`added=0`, log length unchanged); Cursor based on `messages.id` monotonically |
| Explicit disconnected / unreadable status | ✅ PROVEN | Missing/unreadable source reports `status="unavailable"`, never an empty quiet period or false ok |
| Honesty & safe redaction | ✅ PROVEN | Real NULL tool names/repo roots arrive as `unknown` with reasons attached (`field is null`); 0 message content or sensitive keys leaked into payload |
| Restart durability | ✅ PROVEN | Ingested events survive service restart byte-for-byte |
| Ingestion grants no execution rights | ✅ PROVEN | Executors list, tool registry, missions, and approvals completely unchanged |
| No false claims of control/interception | ✅ PROVEN | All events marked `observed_only: true`; no claims of "blocked/allowed/prevented" (Phase 5) |
| Anti-proof (each guarantee proven killable) | ✅ PROVEN | Mutants A, B, C, D all turn RED independently on fresh servers/databases |

#### Anti-proof findings & lessons learned in Phase 4

1. **Port collision on test harness caused false results:**
   In early test iterations, a stale `agent_os.cli serve` process was listening on the hardcoded port `8872`, causing new test boots to fail silently and query the zombie server on an old database (yielding `first_added=0`).
   *Fix:* Converted `boot()` to allocate dynamic ephemeral loopback ports (`get_free_port()`), ensured proper process group shutdown (`kill_process`), and killed lingering background processes.

2. **Discriminative mutant verification vs. monolithic formula:**
   Mutants A, B, C, D originally shared a composite `healthy_shape` check. If one check malfunctioned, all mutants appeared RED for the wrong reason.
   *Fix:* Built dedicated evaluation functions for each mutant:
   - **Mutant A (ordered by timestamp instead of id):** Verifies that row IDs are strictly increasing. Caught when timestamps invert order.
   - **Mutant B (no dedup key):** Verifies replay deduplication. Caught when replay doubles event count.
   - **Mutant C (unreadable source reported as ok):** Verifies unreadable source reporting. Caught when missing DB returns `status='ok'`.
   - **Mutant D (guessing null fields):** Verifies that missing fields (e.g. `git_repo_root IS NULL` in real sessions) are labeled `unknown` with `"field is null"` notes and never replaced with guessed values like `"inferred-name"`. Caught when `inferred-name` appears in payload.

3. **SQLite locking on `/mnt/c`:**
   Opening Windows SQLite databases from WSL2 raised `disk I/O error` on plain read-only connections because locking is unsupported over Plan9/WSL filesystem mounts.
   *Fix:* `StateReader` uses `file:...mode=ro&immutable=1` with explicit documentation of stale-read semantics (acceptable for primary-key cursor traversal, but strictly isolated from the service's own operational store).

### Phase 5 — A real approval gate for one limited action — code complete, PROVEN, AWAITING OWNER ACCEPTANCE

The exit criteria from the roadmap, measured over real HTTP against a live server:

| Exit criterion | Result | Evidence |
|---|---|---|
| The decision binds to action + target, not just a ceiling | ✅ PROVEN | The approval stores one `action`; `validate_dispatch` check 10 refuses when it is not among the job's actions (`test_phase5.py` 03/04/05) |
| Single-use | ✅ PROVEN | `store.consume_approval` is an atomic `UPDATE ... WHERE consumed_at IS NULL`; `p5_proof.py` shows a spent approval cannot authorise a second execution even when the job is forced back to a dispatchable state |
| The gate is on the real dispatch path | ✅ PROVEN | Measured: `dispatch` with no approval raised `no_approval_record` and the executor ran 0 times; `adapter.run` has exactly one call site (`service.py`) |
| Restart / durability | ✅ PROVEN | `RestartDurabilityTest` restarts the process against the same database: the grant survives, is still usable, and is still single-use |
| Timeout / denial fail closed | ✅ PROVEN | Missing, ungranted, expired, mismatched-destination, amended-manifest, out-of-scope and consumed approvals each return a distinct refusal before the executor is invoked |
| The bypass path is identified or declared | ✅ PROVEN | `cli.py` prints and logs `executor.bypass_declared`; a test pins the banner so it cannot be deleted or softened into a reassurance |

#### Two defects found while doing this, both worth keeping

**1. The test harness had been lying since Phase 4, and the Phase 4 write-up already knew.**

Four suites booted a real server on a hard-coded port and treated any `200` on
`/api/status` as readiness. That cannot distinguish our child from an orphan
left by a killed run, so the suite could assert against a stale database. It
surfaced as `added 0 != 3` / `skipped 3` and as `Connection refused`, neither
reproducible in isolation.

The important part: **this exact defect is written down in this file, under
Phase 4, as "port collision on test harness caused false results".** The fix
landed only in `p4_real_proof.py`; the four shared suites kept the bug. A
lesson recorded in one file and applied in one file is not a lesson applied.

The fix is structural: kernel-chosen ports (`--port 0`), readiness proven
against our own child by comparing `db_path`, process-group kill, and one
shared helper (`tests/live_server.py`). Verified with a decoy server holding
the old fixed port 8893 while the full suite ran green.

**2. A Phase 5 edit inverted a documented contract, and only the E2E caught it.**

Moving the consumed-approval check ahead of the A6 idempotency check turned a
replay of a finished job from `200 duplicated=true` into `409`, breaking
`e2e_verify.py` step 7 and contradicting README/READINESS. No unit test failed,
because the tests had been edited to expect the new behaviour - which is
exactly how a suite can be green and wrong at the same time.

Confirmed against the pre-change tree (`git worktree add --detach HEAD`): step 7
passed before. Restored. The rule: **single-use is enforced by the action
running exactly once, not by turning a retry into an error.**

#### Method note

`p5_proof.py` was checked with `p5_mutation_check.py`, which removes policy
check 9, runs the proof, and restores the file byte-for-byte. With the guard
removed the proof reports `FAIL 3: a spent approval authorised a second
execution` - so it is a proof and not a tautology. This is the same standard
F1, F3, F5 and F11 were held to.

## Method notes worth keeping

- The `agy` reviewers were wrong or unhelpful about 40% of the time. One
  refused a brief framed as "adversarial review" after reading 18,964 tokens
  and completed the same scope in 233 seconds when framed as "do these four
  invariants hold, citing file:line". Framing changes what a model will do.
- One reviewer claimed to have written a summary file that did not exist. A
  claim about an artifact needs the artifact.
- Long reviewer runs get truncated mid-answer and still report success. Read
  the envelope, not just the prose.
- Two of the four rejected claims were checkable in one command each — for
  example, whether any released revision ever created a table without a column.
  Plausibility is not history.

### Measured, then closed

Before the fix, over the real API. A symlink named `shared`, with no hint in
the name, pointing at a directory holding an `id_rsa` and a `credentials`:

    dispatch 200, final state completed_unverified
    GET /api/jobs/<id>/evidence ->
      "diff": "exit_code=0\n\n--- stdout ---\npassword=hunter2\n"

So the finding was understated in two ways. A link to a single FILE leaks too
(it takes the copy2 branch, not copytree), and the content does not merely land
on disk - the executor publishes stdout as evidence and the API hands it back
over HTTP. The leak has a network path.

`shutil.copytree(symlinks=True)` was measured as a non-fix: a command reading
through a preserved link still returned the target's contents, because the read
happens with the server's own privileges. Preserving links stops the copy, not
the read. The copy cannot be made safe by a flag, so the run is refused.

`_find_escaping_links` reuses `is_within`/`canonicalize` from paths.py - the
same predicate Phase 1 uses for the project registry, so "inside" means one
thing in this codebase. It walks with `followlinks=False` and also removes each
link from `dirnames`, because a link to an ancestor would otherwise walk
forever. Measured: a link to a sibling sharing a prefix (`/src` vs `/srcs`) is
correctly an escape.

Chosen behaviour (option A): any link leaving the workspace refuses the run and
the message names the offending paths. A link that stays inside is allowed, so
an ordinary project is not broken for a self-referential link. The cost is
honest: a project that symlinks `vendor/` or `node_modules/` out of its tree
will be refused, and the operator is told why.

The guard runs BEFORE the sandbox is created, and a test asserts that order by
witnessing the filesystem - a guard that raised after the copy would still
produce the right message while the secrets sat in the run directory.

**Not fixed here, and stated rather than implied:** the guard stops the copy.
A command can still read any path the server can read, because it runs as the
server. That is F2, and it is Phase 6 work. This finding closed the copy, not
the read.

Evidence: `tests/test_symlink_boundary.py` (12 tests), mutation 8/8 killed,
and `f5_proof.py` over real HTTP - PROVEN on the real code, NOT PROVEN with the
guard disabled, where the run completed and `password=hunter2` came back in the
evidence body.

## F9 — the copy recurses through a link to an ancestor — CLOSED

Found by F5's own test, not by review. `_copytree_into` tests `child.is_dir()`,
which FOLLOWS a symlink, so a link pointing at an ancestor is recursed into
until the OS refuses:

    shutil.Error: [Errno 40] Too many levels of symbolic links

It fails closed and fast, so it is a robustness defect, not a containment hole.
Re-measured for this pass to be sure the sibling case was not worse: a link to
a sibling directory IS an escape and F5's guard refuses it, so the only links
that reach the copy point inward and cannot exfiltrate anything.

### Fixed — and the first attempt was wrong

A symlink is now copied AS a link (`os.symlink(os.readlink(child), target)`),
and the recursive `copytree` gets `symlinks=True`.

The first version skipped links at the top level and left the recursive copy on
its default — so a link INSIDE a subdirectory was still followed, the same
defect one level down. It passed its own ancestor-link test. The nested test
that now exists is the one that would have caught it.

### A second defect found while fixing this one

The ignore list was passed only to the recursive `copytree`, never applied at
the top level, so a `.git` or `__pycache__` at the workspace root was copied
into every sandbox. Verified against `git show HEAD` to be a pre-existing bug
and not a regression from this change. Both levels now read one
`_COPY_IGNORED` constant, so they cannot drift apart again.

### Evidence

15 tests covering F9 and F10 together, mutation 9/9. The nested-link case and
the `symlinks=True` argument each have their own test, because "the top level
works" is exactly the claim that hid the first bug.

## F10 — POST /api/projects ignores a caller-supplied scope — CLOSED

Found while writing F5's proof. `register_project` accepted a `scope` parameter
and documented that the default came from configuration — but the HTTP handler
never passed it. Measured across all nine call sites: not one supplies it, so
the parameter was unreachable from the API and from the CLI.

The fail-closed direction was never in doubt — a caller can only be more
restricted by the omission. The cost was that the signature advertised a
control nobody could turn, which cost an hour of debugging a proof.

### Fixed by removing it, not by wiring it up

Passing the caller's scope through would have been the obvious "fix" and the
wrong one: it lets a client name its own boundary, which is the opposite of what
a scope is for. The scope is a property of the deployment, configured through
`AGENT_OS_PROJECT_SCOPE`. So the parameter is gone, and the docstring says why
so the next reader does not re-add it as an improvement.

A test walks the tree and fails if any caller passes `scope=` again, and another
asserts the projects endpoint does not read a scope field.

`~/workspace` exists on this machine and `project_scope()` falls back to it, so
a test that only unsets the environment variable measures the wrong branch.
The unset-scope test patches the resolver instead — that branch was the one
surviving mutant (M9) after the first mutation run.


## F11 - a missing resource answers 500 instead of 404

Status: **CLOSED** (owner-authorised, 2026-09-28). See the closure note at the end of this file.

### What it is

A route that resolves an object by id and does not find it passes `None` into a
public serialiser, which dereferences it. The exception escapes as a 500.

Measured on a live server, with a valid token:

| request | now | correct |
|---|---|---|
| `GET /api/approvals/` | 500 | 404 |
| `GET /api/missions/` | 500 | 404 |
| `GET /api/jobs/` | 500 | 404 |
| `POST /api/missions/<absent>/activate` | 500 | 404 |

Four of eleven probed single-resource paths. Every path with a well-formed but
absent id (`/api/approvals/approval_absent`) already answers 404 correctly, so
the defect is specifically the empty/absent-segment case.

### Why deferral is safe - measured, not assumed

- **No disclosure.** The body is `{"error":{"code":"internal","message":"internal
  error"}}`. No traceback, no file path, no system detail reaches the client.
- **Not an auth defect.** Authentication is checked before routing, so a request
  without a token can never reach this code. Ten unauthorised presses wrote
  nothing and created nothing.
- **Pre-existing.** It is in the original routing layer, not in the Phase 3 code.
- **Not reachable from the UI as built.** The page builds these URLs by
  concatenating an id taken from a row the server itself returned, and every
  such row has an id.

### One correction worth recording

The owner's first hypothesis was that repeatedly pressing the buttons with no
token caused the 500s. Measured: five presses each returned 401 every time, and
the same URLs with a valid token return 500. The hypothesis was refuted, and
inverted - a valid token is required to reach the defect at all.

### Condition for opening it

Any of: a caller passing a client-supplied id; a row that can render without an
id; or a 500 that surfaces in the owner's logs during normal use.

### Found while

Investigating the owner's report that the Tools panel was empty. The report
turned out to be a missing token, not a defect - but following the diagnostics
warning it produced led here.


### Two UI defects found from the owner's own use, both DEFERRED

Neither is a Phase 3 exit criterion, and neither is a safety problem.

**`runDiscovery()` has no TOKEN guard.** `refresh()` is wrapped in
`if (TOKEN)`, but the Discover button is not. With no token it issues a real
unauthenticated request and reports a generic failure. The fix is to check the
token first and say where to get one.

**Diagnostics drops the field that would identify the failure.** `uiLog()`
stores `{status: resp.status}` for the "response body was not JSON" warning, but
the render line only appends `r.detail`. The status is therefore captured and
never shown. The owner saw five such warnings with no way to tell which request
they came from - an observability tool that hides the fault is worse than none.

The five warnings themselves were **not reproduced**. Measured against a live
server: all six paths of the 4-second loop, eight rounds, plus six concurrent
requests, plus every 401 and 404 path - all returned valid JSON. The server is
`ThreadingHTTPServer`, so the slow discovery call does not block the others.
Leading explanation, recorded as unconfirmed: the warnings came from the
no-token session, before a token was entered.


## F11 - a missing resource answered 500 instead of 404

Status: **CLOSED** (owner-authorised, 2026-09-28).

### The real cause was not what the status code suggested

The deferred note said a `None` reached a public serialiser. That was wrong.
`_mission_public` already raised `KeyError` for `None` and the dispatcher
already caught `KeyError`. The server's own log named the real one:

```
api.internal_error  error=IndexError: list index out of range
```

`"/api/missions/".strip("/")` is `"api/missions"`, so `parts[2]` raised before
any lookup happened. The finding was still reachable only with a valid token,
so it was invisible in every earlier no-token session.

### A second defect on the same path

`activate_mission` updated the state, recorded the event and logged **before**
asserting the mission existed. Activating a mission that does not exist wrote a
`mission_activated` event into the feed for a mission that never existed, and
then raised `AssertionError` (a 500) - an `assert` that also disappears under
`-O`. The existence check now precedes every write.

### What changed

- `Api._segment()` reads an id segment or raises a 404; wired into all nine
  single-resource routes, replacing raw `parts[2]` / `path.split("/")[3]`.
- `ControlService.activate_mission` resolves the mission first and raises
  `KeyError` before touching state, feed or log.

### Evidence

| | |
|---|---|
| tests | 20 new in `tests/test_f11.py`; suite is 396 |
| proof | `f11_proof.py`, 15 checks, PROVEN |
| anti-proof | M1, M3 and M5 all go RED with the guard removed |
| regression | `f1_proof`, `f3_proof`, `f5_proof` still PROVEN; E2E PASS |

### Two mutants that were honestly recorded

- **M2 is equivalent.** `_segment` returning `""` instead of raising still yields
  404, because an empty id looks up a row that cannot exist. Recorded as
  equivalent, not dressed up as a kill.
- **M3 initially survived, and the reason was the tests, not the code.** The
  write-ordering tests shared a class-level server with a test that activates a
  real mission, so the feed was already non-empty and a count comparison could
  not attribute the mutant's event. They now live in `NoWriteOnRefusalTest`
  with their own server, its own database, and an assertion that the feed
  starts empty. M3 is then killed in isolation **and** in the full suite.

A test that only fails when run alone is a test that has quietly stopped
testing.


### The two UI defects, now closed

**`runDiscovery()` had no TOKEN guard** while `refresh()` is wrapped in
`if (TOKEN)`. It now checks first and says so, with a catalog string in both
languages (`ui.toolsNeedToken`), instead of issuing an unauthenticated request
and reporting a generic failure.

**Diagnostics captured `{status}` and rendered nothing.** The render line now
prints the status and the method+path, so a warning can be traced to the
request that caused it. This is the defect that made the five "response body
was not JSON" warnings undiagnosable at the time.

Both are held by tests in `test_f11.py` (M5, M6, M7, M8) and by the proof's
anti-proof, which goes red without each one.
