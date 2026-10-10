# Adapter Contract (Skill 08)

Provider-neutral interface between the Agent-OS Neural Command UI and
any data provider. The shipped provider is a **functional mock**
(`src/adapter/mockAdapter.js`); a real Agent OS backend adapter must
implement the same surface with the same result shapes.

Status: **MOCK / demo**. No real endpoints are called by the UI.

---

## 1. Interface (minimum, all methods required)

| Method | Purpose | Mock status |
| --- | --- | --- |
| `getCapabilities()` | Declares the four-fact capability model + `navCapabilities` feature gates | supported |
| `listResources(kind, query)` | Paged list of registered resources (`agent`, `connection`) | supported |
| `getResource(kind, id)` | One resource record | supported |
| `validateChanges(changeSet)` | Per-operation validation, no mutation | supported |
| `applyChanges(changeSet)` | Sequential apply; per-op `accepted`/`rejected` results | supported |
| `getExecutionSnapshot(scope)` | Runtime snapshot | **declared unsupported** (typed error) |
| `subscribeEvents(scope, handler)` | Event stream; returns unsubscribe | **declared unsupported** (typed error) |
| `requestAction(action)` | Actionable command; returns receipt | **declared unsupported** (typed error)` |
| `queryMemory(request)` | Shared-memory retrieval, per-agent/per-scope policy | supported (when a provider is configured) |
| `syncWorkspace(base)` | Mock-only: keeps the resource index in sync with app state | mock extension |

`applyChanges(changeSet)` shape:

```js
{
  base: { agents, connections, manifest, pages },
  changes: [{ opId, status: "pending", op, ...payload }]
}
```

Returns `{ ok: true, status: "ok" | "partial" | "failed" | "noop",
results: [{ opId, op, status: "accepted" | "rejected", reason }],
agents, connections, manifest?, pages? }` — the returned state
contains **only accepted operations**; rejected ops never mutate it.

Sequential semantics: each accepted op mutates the working state, so
later ops see earlier accepted ops (a second `addNavItem` with a route
the first one just created is `rejected` with its reason).

---

## 2. Capability model — four facts, kept separate

`getCapabilities().capabilities[method]` returns:

- `supported` — the provider implements it.
- `authorized` — the current user may use it (UI gating only;
  the backend must re-enforce — hiding a control is not authorization).
- `available` — the service is reachable now.
- `configured` — required settings exist.
- `explanation` — readable reason when any fact is false.

`getCapabilities().navCapabilities` lists the workspace feature gates
this provider can back (`canvas`, `timeline`, `resource-tables`, …).
The sidebar/page manifest entries reference these by name; the UI reads
the list **from the adapter**, so a second adapter with a different list
changes UI gating without any component edits (covered by
`tests/contract.test.js`). The mock intentionally omits `live-telemetry`.

---

## 3. Error taxonomy

Method-level failures are typed, never thrown:

```js
{ ok: false, error: { type, message } }
```

| `type` | Meaning |
| --- | --- |
| `invalid_change_set` | Malformed changeSet (missing base/changes) |
| `unsupported` | Method declared unsupported by this provider |
| `unsupported_kind` | Unknown resource kind |
| `not_found` | Resource id does not exist |
| `invalid_request` | Bad request payload (e.g. memory query) |
| `not_configured` | Required provider/settings missing |
| `access_denied` | Policy denied (memory grants are per agent + scope) |

Operation-level failures inside `applyChanges` are **not** errors:
they appear as `{ status: "rejected", reason }` and produce
`status: "partial"` (some accepted) or `"failed"` (all rejected).
The UI must never show full success when anything was rejected.

Validation failures from `validateChanges` return
`{ ok: false, errors: [readable strings] }`.

---

## 4. Rules for a real backend adapter

- **No URLs, endpoints, credentials, or tokens in UI code.** The UI
  only talks to the adapter object it is given. (`tests/contract.test.js`
  scans renderer sources for URL strings.)
- **Timeout / abort:** every network method must accept cancellation
  and distinguish two states: *cancelling* (request sent, result will
  be ignored) and *cancelled* (settled without applying). A stale
  response must never overwrite newer state.
- **Retry = new run:** a retried apply is a new changeSet/operation
  set with fresh opIds; never replay rejected ops silently.
- **Authorization is backend-side.** Nav/permission gating in the UI is
  presentation only; the backend must enforce the same policy.
- **All mock data is labeled MOCK/demo**; a real adapter drops the
  label only when it talks to verified, documented endpoints.

---

## 5. Fitting an Agent OS backend (`\\wsl.localhost\...\Agent-OS`)

Required sequence (no endpoints implemented without approval):

1. **Read-only discovery** of the backend: enumerate services,
   routes, auth, and data models.
2. **Endpoint inventory**: list candidate endpoints per contract
   method (`listResources`, `applyChanges`, `queryMemory`, …).
3. **Mapping table**: endpoint → method → result shape → error types;
   note gaps where the backend has no equivalent (declare them
   `supported: false` with an explanation instead of faking them).
4. **Capability facts** for the real provider: which of the four facts
   hold, and the real `navCapabilities` list.
5. **Stop and request approval** — then implement the adapter behind
   the same `createXAdapter` factory shape, swap it in `App.jsx`
   (`useMemo(() => createXAdapter(...))`), and keep the mock for tests.

---

## 6. Contract tests

- `tests/adapter.test.js` — four-fact model, per-op results,
  partial apply, memory policy, paged resources.
- `tests/contract.test.js` — default `navCapabilities`; adapter
  copy-isolation; **second adapter changes gating without component
  changes**; declared-unsupported methods return typed errors that
  agree with `getCapabilities`; renderer sources contain no URLs.

Known gaps / open points:

- `getExecutionSnapshot` / `subscribeEvents` / `requestAction` stay
  unsupported in the mock (typed errors) until a scripted runtime
  provider is approved.
- Workspace **import** currently *replaces* connections/manifest/pages
  (merge semantics remain an open product question).
