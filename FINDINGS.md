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
