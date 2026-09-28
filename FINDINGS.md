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
| F3 | `kill()` does not kill the process group; a backgrounded child survives the timeout | medium | **OPEN** |
| F4 | The `command` type annotation was neither a guard nor correct | medium | **CLOSED** — `cddcb46` (edge validation) + `6079c22` (storage) |
| F5 | `copytree` follows symlinks, so a link to `~/.ssh` copies the keys in | low | **OPEN** |
| F6 | Cleanup failures are silent (`ignore_errors=True`, four sites) | low | **OPEN** |
| F7 | Two resource leaks: sqlite connect, and a window before `try/finally` | low | **OPEN** |
| F8 | `jobs.command` could not survive storage at all | — | **CLOSED** — `6079c22` |

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

## F3 — the timeout kills only the direct child — OPEN

`proc.kill()` kills the immediate child. `["bash", "-c", "sleep 999 &"]` leaves
a grandchild running while the timeout is reported honestly as a timeout.

Same root cause produces a second leak: there is no `finally` around the
`Popen`, so a `KeyboardInterrupt` during `wait()` abandons the process.

Fix shape: start the child in its own session (`start_new_session=True`) and
signal the group, plus a `finally` that guarantees cleanup.

## F4 — the type annotation was documentation, not a guard — CLOSED

`models.py` annotated `command: Optional[str]` while the only shape that works
is a list; and the API accepted any JSON type, so an `int` or `dict` reached
`Popen` and produced a 500 instead of a clean refusal.

Closed by two commits: `cddcb46` validates the shape at the HTTP edge with
permanent tests, and `6079c22` makes the stored form canonical JSON so it can
survive sqlite at all. The annotation is now true rather than aspirational.

## F5 — `copytree` follows symlinks — OPEN

`shutil.copytree` defaults to `symlinks=False`, so a symlink is followed and the
target's **contents are copied**. A project containing `ln -s ~/.ssh link`
copies the keys into a directory the job can read and whose output can be
reported. Not an escape — a copy and a disclosure.

## F6 — cleanup failures are silent — OPEN

Four `rmtree(..., ignore_errors=True)` sites. A failed delete is swallowed and
garbage accumulates with no signal. `keep_workspace=True` also has no ceiling.

## F7 — two resource leaks — OPEN

- `store.py` — the sqlite connection is opened with no `try/finally`, so a
  schema failure leaks it.
- The socket setup path has a small window before `try/finally`, so `Ctrl-C`
  during startup leaves it bound.

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
