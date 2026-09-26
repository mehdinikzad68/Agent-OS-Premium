# Agent OS — Hermes Integration Layer: Design Note

**Status:** design **approved by the owner on 2026-09-26**. Section 6 records the
four decisions. **Nothing in this document is implemented.** No code in
`control-service/` has been changed as a result of it.

**Date:** 2026-09-26
**Author:** Hermes (development coordinator)
**Pinned to:** Hermes Agent `v0.21.5+2453.gd0288be` (2026.9.24)
**Repository:** `mehdinikzad68/Agent-OS-Premium` (private)
**Language:** English, with the Persian/English bilingual work deferred to a later phase.

---

## 0. How to read this document

Section 1 states what was **measured** on this machine. Section 2 states what is
**designed**. Section 3 states what is **still unknown**. These are not mixed —
if a claim has no measurement behind it, it is in section 3, not section 1.

Nothing here claims the approval gate works. Per the owner's standing rule, an
approval gate is not called effective until a test proves it stops an action
**before execution**. Section 4 is that test, and it has not been run.

---

## 1. Measured facts

All items below were verified on the owner's machine on 2026-09-26.

### 1.1 The gap that motivates this design

`hermes approvals test` is a **dry-run**: it returns a verdict and never
executes the command. With the owner's current setting (`approvals.mode: smart`):

| Command | Verdict | Consequence |
|---|---|---|
| `git push origin main` | `allow` (exit 0) | **runs with no prompt** |
| `docker rm -f wordpress` | `allow` (exit 0) | **runs with no prompt** |
| `docker compose down -v` | `ask-approval` | prompts |
| `git push --force origin main` | `ask-approval` | prompts |
| `rm -rf /tmp/xyz` | `ask-approval` | prompts |

A plain push to a public repository, and the deletion of the owner's WordPress
container, are both currently unguarded. This is the concrete gap Agent OS
exists to fill. The built-in gate is a convenience guardrail, not a control plane.

### 1.2 Available Hermes surfaces

**Observation — `hooks.outbound` in the profile `config.yaml`.** Hermes POSTs a
signed JSON payload to any HTTP endpoint on matching lifecycle events. Push-based;
no polling on the receiving end. Configurable per event, with a regex `matcher`
and HMAC signing via `secret_env`.

**Interception — `pre_tool_call` shell hook.** Runs as a subprocess before the
tool executes. **Exit code 2 blocks the tool call.** `fail_closed: true` inverts
the default fail-*open* behaviour so that a crash, timeout, or non-JSON output
blocks the call instead of silently allowing it.

**Safe test path — `hermes hooks test`.** Fires hooks against a **synthetic
payload**. Nothing real executes.

**Read-only history — profile `state.db`.** 24 tables in the active profile
(`sessions`, `messages`, `async_delegations`, `session_model_usage`, …) plus
`logs/agent.log`, `logs/desktop.log`, `logs/errors.log`.

**Coarse stop — `hermes pause` / `hermes resume`.** Pauses cron/kanban dispatch
and new gateway turns. Not a per-action control.

### 1.3 Current state

- `hooks:` block is **absent** from the active profile's `config.yaml`. Neither
  outbound webhooks nor shell hooks are configured.
- Inbound webhook platform is **disabled** (needs `platforms.webhook.enabled`).
  Not required for this design.
- `plugins.enabled` is `[]`. Not required for this design.

### 1.4 A trap that would have silently produced a dead system

Hermes documents **four** distinct hook systems. The gateway hook system
(`~/.hermes/hooks/<name>/HOOK.yaml` + `handler.py`) is **gateway-only**: the CLI,
Desktop, TUI, and cron never load it. The owner works in Hermes Desktop, so a
gateway hook would be **installed and never fire**.

Shell hooks and `hooks.outbound` both run in Desktop. This design uses only
those two.

---

## 2. Design

### 2.1 Two channels, deliberately separate

```
OBSERVATION (Hermes -> Agent OS)         CONTROL (Agent OS -> Hermes)
hooks.outbound POSTs, signed             pre_tool_call shell hook
  Agent OS receives, redacts, stores      blocks on exit 2 / fail_closed
  NEVER blocks the agent                 NEVER controls the dashboard
```

Keeping them separate means a broken dashboard can **never** block the owner's
work in Hermes, and a broken hook can **never** corrupt the audit trail. The
observation path is fail-open; the control path is fail-closed. This asymmetry
is intentional and is the single most important decision in this document.

### 2.2 Observation channel

Configured as one entry in the active profile's `config.yaml`:

```yaml
hooks:
  outbound:
  - name: agent-os
    url: http://127.0.0.1:8471/ingest/hermes
    events: [pre_tool_call, post_tool_call, on_session_start, on_session_end,
             subagent_start, subagent_stop, agent_loop_stopped]
    matcher: "terminal|write_file|patch|delegate_task"
    secret_env: AGENT_OS_INGEST_SECRET
    timeout: 5
```

Design constraints:

- **Loopback only.** Binding Agent OS to `127.0.0.1` means no other machine on
  the network can inject events.
- **A separate, non-default port** (8471 vs the app's documented 8470) so the
  ingest endpoint can never be confused with the app itself.
- **Signed.** `secret_env` names an environment variable; the secret stays in
  `.env` and never enters `config.yaml`. An unsigned endpoint is rejected —
  `hermes hooks list` reports `UNSIGNED`, and a dead `UNSIGNED` entry is treated
  as a fault, not a warning.
- **Bounded.** Payloads are truncated at ingest. There is no artifact store yet
  (documented in `READINESS.md`), so oversized data is lost by design, not
  silently truncated in the middle of a diff.

### 2.3 Redaction is a first-class stage, not a filter

The wire format includes `tool_input` — the **raw arguments of the tool call**.
If Hermes is about to run a command containing a token, that token arrives in
the event payload.

Therefore redaction sits **immediately after receipt and before any write**,
in this order:

1. Strip environment-variable references and anything matching credential shapes.
2. Replace the value with `[REDACTED]`, keeping length-only hints.
3. Never log the unredacted payload, not even at debug level.
4. Re-run the same test fixture for the approval preview path — a preview and an
   event must never disagree about what was redacted.

The owner's requirement is that credentials must not leak through commits,
pushes, PRs, logs, events, or screenshots. Events are the newest of those
channels and therefore the newest place this can go wrong.

### 2.4 Control channel

A single `pre_tool_call` shell hook that does nothing but delegate:

```yaml
hooks:
  pre_tool_call:
  - matcher: "terminal"
    command: "~/.hermes/agent-hooks/agent-os-gate.py"
    timeout: 10
    fail_closed: true
```

**Two-stage rollout (owner decision).** Stage 1 gates **`terminal` only**.
Stage 2 adds `write_file` and `patch` after the owner has used Stage 1 for a few
days and trusts its behaviour. Rationale: `terminal` is where real danger lives
(`git push`, `docker rm`, `rm -rf`, installs), while file writes are frequent
enough that gating them from day one would be noisy. Stage 2 is close to free
once Stage 1 is trusted; it is never required.

The hook reads the JSON payload on stdin, applies a policy, and either exits 0
(proceed) or exits 2 (block) with a reason on stderr.

**`fail_closed: true` is mandatory.** The default is fail-**open**: a crashed
hook logs a warning and the action proceeds. For an observability hook that is
correct. For a security gate it is a silent bypass. The cost is that a broken
hook stops all agent work until it is fixed — an acceptable trade for a tool
this owner uses to gate destructive actions.

**Scope limit, stated plainly:** this hook gates **tool calls issued inside
Hermes**. It does **not** gate commands typed by hand in a terminal, actions
taken by DSH on its own, or anything in Antigravity. The UI must display this
boundary rather than implying total coverage. A connector's inability to
intercept an operation must be shown, not disguised.

### 2.5 Degradation and the manual recovery route

The owner's standing requirement is an independent recovery route. The states:

| Agent OS | Hermes behaviour | What the owner sees |
|---|---|---|
| Running | Events flow; gate consults policy | Normal |
| **Down** | Events lost. Gate **fails closed** -> agent work stops | Explicit banner: "control plane offline - agent work is blocked" |
| Crashing | Same as down, after `timeout: 10` | Same banner |

**Owner decision (2026-09-26): security outranks availability.** Hermes stopping
while Agent OS is down is the accepted cost. The consequence is stated in the UI
rather than hidden, and section 2.6 defines the wording.

Manual recovery, independent of Agent OS:

```bash
# inspect what is configured
hermes hooks test pre_tool_call
# remove the hook, restart Hermes, and proceed manually
```

Recovery never depends on Agent OS being functional.

### 2.6 UI honesty rule (owner decision, 2026-09-26)

The owner decided: **show reality, report the risk, and offer a route to fix it.**
Three refinements make that implementable rather than aspirational.

**(a) Three states, not two.** A green "all clear" must never be the default.

| State | Meaning | Example |
|---|---|---|
| `guarded` | genuinely under control | Hermes connected, gate active |
| `exposed` | the risk is known and named | DSH acted without approval |
| `unknown` | **we do not know** | Hermes connected, but no event for 5 min |

`unknown` must never collapse into `guarded`. If the inbound stream stops while
nothing dangerous happens, a naive system shows calm — that is a lie. Silence
from a broken sensor is not evidence of safety.

**(b) The remediation route is itself controlled.** Guidance must not tell the
owner to run a sensitive command in a raw terminal, because that path bypasses
the very control being reported. A fix for a `docker` risk is proposed **through
Hermes**, where it is recorded and gated. Otherwise the advice defeats itself.

**(c) Severity is three levels, not one colour.**

| Level | Meaning | Behaviour |
|---|---|---|
| `low` | information, no change | display only |
| `medium` | change inside an approved project | warn + record in history |
| `high` | outside the project, sensitive file, credential, network publish, Git push, Docker/DB | **halt + mandatory owner approval** |

The `high` list is taken from the owner master plan, section 8.

**(d) The coverage boundary is part of the honesty rule.** The gate covers tool
calls issued inside Hermes only. It does not cover commands typed by hand in a
terminal, actions DSH takes on its own, or anything in Antigravity. The UI states
this rather than implying total coverage.

---

## 3. Not yet known

These are open questions. None of them is assumed anywhere in section 2.

| # | Question | Evidence needed |
|---|---|---|
| 1 | Does `pre_tool_call` really fire in Hermes **Desktop**, not only the CLI? | A real blocked tool call, observed |
| 2 | Does `fail_closed: true` behave as documented on this build? | Deliberately break a hook, observe blocking |
| 3 | What is the real redaction surface — does `tool_input` contain env values in practice? | A controlled run with a fake credential |
| 4 | Is `hooks.outbound` delivery reliable, and what is the retry/loss behaviour? | Observed delivery over repeated events |
| 5 | Does the consent prompt (`hooks_auto_accept: false`) behave acceptably for daily use? | A full day of real use |
| 6 | Can Agent OS distinguish "Hermes did nothing" from "Hermes was never observed"? | A deliberate outage test |

Item 6 is the honesty requirement from the master plan: **a missing event stream
must be labelled `unknown`, never `idle`.**

---

## 4. Acceptance test for the gate (not yet run)

Per the owner's rule, the gate is not called effective until this passes. The
test is designed to be run **after** implementation, against a synthetic payload
first, then against one real and reversible action.

| # | Step | Expected |
|---|---|---|
| 1 | `hermes hooks test pre_tool_call` with a synthetic payload | Hook fires; parsed block shape shown |
| 2 | Synthetic payload naming a sensitive action | Blocked, with reason |
| 3 | Break the hook script (syntax error) | **Blocked**, not allowed — proves `fail_closed` |
| 4 | Synthetic payload naming a low-risk action | Allowed |
| 5 | Agent OS **stopped**, then trigger a gated action | Blocked; UI shows "offline", never "idle" |
| 6 | One real, reversible action (write a throwaway file in a temp dir) | Blocked until approved; allowed after approval |
| 7 | Repeat step 6 after a restart | Same behaviour |

Step 6 is the only step that touches anything real, and what it touches is a
throwaway file in a temp directory. **Steps 1-5 and 7 execute nothing.**

---

## 5. Explicitly out of scope for this layer

- DSH interception (a separate, later question; not verified)
- Antigravity (IDE-only; no API assumed)
- Docker container policy (mounts, UID mapping, network) — Phase 6 material
- Multi-user, remote binding, cloud sync
- Any change to the public `Agent-OS` repository

---

## 6. Owner decisions (taken 2026-09-26)

| # | Question | Decision |
|---|---|---|
| 1 | Fail-closed, which can stop all agent work? | **Accepted.** Security outranks availability (section 2.5) |
| 2 | Which tools in Stage 1? | **Two-stage.** Stage 1 = `terminal` only; Stage 2 adds `write_file` and `patch` later (section 2.4) |
| 3 | Ingest port? | **`127.0.0.1:8471`** (section 2.2) |
| 4 | Honest coverage wording in the UI? | **Accepted**, in the owner own framing: show reality, report the risk, and propose a controlled route to fix it (section 2.6) |

All four are now settled. What remains is **implementation**, which this
document does not authorise. Section 3 lists six facts that must be measured
during implementation, not assumed beforehand.**
