// Mock backend adapter — implements the provider-neutral adapter
// contract (skill 08).
//
// MOCK: deterministic, in-memory, no network, no filesystem, no
// secrets. A real Agent OS adapter implements the same methods and
// the UI does not change. The UI never builds URLs and never reads
// secrets — only adapters do.
//
// Capability model — four separate facts per method:
//   supported   the provider implements it
//   authorized  the current user may use it
//   available   the service is reachable now
//   configured  required settings exist
//
// Failures are returned as TYPED results ({ ok:false, error:{type,message} }),
// never thrown into the renderer.
//
// applyChanges returns a per-operation result: each change is
// accepted or rejected with a reason. The overall status is
// "ok" | "partial" | "failed" | "noop" — never full success when
// any operation was rejected.

import { canConnect, connectionId } from "../model/connections.js";
import { getCoordinator } from "../model/registry.js";
import { hasReadAccess } from "../model/memory.js";
import { validateNavItem, validatePages } from "../model/manifest.js";

export const ADAPTER_SCHEMA_VERSION = 1;

// Draft ops this adapter can apply. Anything else is reported as
// unsupported — visibly, with a reason.
const APPLY_OPS = new Set([
  "addEntity",
  "removeEntity",
  "addConnection",
  "removeConnection",
  "setConnectionState",
  "changePermission",
  // skill 07: navigation / page manifest ops
  "addNavItem",
  "moveNav",
  "setNavVisibility",
  "addPage",
]);

const RESOURCE_KINDS = ["agent", "connection"];

const CAPABILITY = (supported, explanation = null) => ({
  supported,
  authorized: supported,
  available: supported,
  configured: supported,
  explanation,
});

const unsupported = (message) => ({
  ok: false,
  error: { type: "unsupported", message },
});

// Workspace feature gates this provider declares it can back
// (skill 08: capability = a fact reported BY the adapter, not a
// constant baked into components). The manifest references these
// by name; swapping the adapter changes UI gating with zero
// component edits. "live-telemetry" is intentionally absent in
// the mock — the UI must show that entry as unavailable WITH an
// explanation, never as a working demo.
export const DEFAULT_NAV_CAPABILITIES = [
  "canvas",
  "timeline",
  "resource-tables",
  "schema-forms",
  "memory-read",
  "run-clusters",
];

const AGENT_STATUSES = ["running", "awaiting", "complete", "offline"];

/** Entity index the adapter validates against: registered entities
 *  plus the current operational agents (custom tools are tools). */
function entityIndex(registry, agents) {
  const byId = {};
  for (const e of Object.values(registry.byId)) {
    byId[e.id] = { id: e.id, kind: e.kind };
  }
  for (const a of agents || []) {
    if (!byId[a.id]) byId[a.id] = { id: a.id, kind: "tool" };
  }
  return byId;
}

/** Map a draft addEntity payload onto the UI agent record shape. */
function entityToRecord(e) {
  const record = {
    id: e.id,
    name: e.name,
    sub:
      typeof e.description === "string"
        ? { en: e.description, fa: e.description }
        : e.description || { en: e.name, fa: e.name },
    status: AGENT_STATUSES.includes(e.status) ? e.status : "offline",
    tok: typeof e.tok === "string" ? e.tok : "0",
    load: typeof e.load === "number" ? e.load : 0,
    seen: typeof e.seen === "string" ? e.seen : "00:00",
  };
  if (e.cmd) record.cmd = e.cmd;
  if (e.icon) record.icon = e.icon;
  if (e.parent) record.parent = e.parent;
  return record;
}

/**
 * Apply one draft change to the working state. Pure: returns the
 * next { agents, connections, manifest, pages } (any subset) or a
 * rejection reason. Ops that do not touch a field omit it.
 */
function applyOne(registry, agents, connections, change, manifest, pages) {
  if (!APPLY_OPS.has(change.op)) {
    return { ok: false, reason: `unsupported draft op for this adapter: ${String(change.op)}` };
  }
  const byId = entityIndex(registry, agents);

  switch (change.op) {
    case "addEntity": {
      const e = change.entity;
      if (!e || typeof e.id !== "string" || !e.id || typeof e.name !== "string" || !e.name) {
        return { ok: false, reason: "addEntity: entity needs a non-empty id and name" };
      }
      if (byId[e.id]) return { ok: false, reason: `addEntity: duplicate id "${e.id}"` };
      return { ok: true, agents: [...agents, entityToRecord(e)], connections };
    }
    case "removeEntity": {
      const id = change.entityId;
      if (!byId[id]) return { ok: false, reason: `removeEntity: unknown entity "${id}"` };
      if (getCoordinator(registry)?.id === id) {
        return { ok: false, reason: "removeEntity: the coordinator cannot be unregistered" };
      }
      return {
        ok: true,
        // children (relay tools) are removed with their parent
        agents: agents.filter((a) => a.id !== id && a.parent !== id),
        // cascade: connections referencing the entity go with it
        connections: connections.filter((c) => c.from !== id && c.to !== id),
      };
    }
    case "addConnection": {
      const c = change.connection;
      const spec = {
        from: c && c.from,
        to: c && c.to,
        type: c && c.type,
      };
      const check = canConnect({ byId }, connections, spec);
      if (!check.ok) return { ok: false, reason: `addConnection: ${check.reason}` };
      const connection = { ...c, id: c.id || connectionId(spec.from, spec.type, spec.to), state: c.state || "enabled" };
      return { ok: true, agents, connections: [...connections, connection] };
    }
    case "removeConnection": {
      if (!connections.some((c) => c.id === change.connectionId)) {
        return { ok: false, reason: `removeConnection: unknown connection "${change.connectionId}"` };
      }
      return { ok: true, agents, connections: connections.filter((c) => c.id !== change.connectionId) };
    }
    case "setConnectionState": {
      if (!connections.some((c) => c.id === change.connectionId)) {
        return { ok: false, reason: `setConnectionState: unknown connection "${change.connectionId}"` };
      }
      return {
        ok: true,
        agents,
        connections: connections.map((c) =>
          c.id === change.connectionId ? { ...c, state: change.state } : c
        ),
      };
    }
    case "changePermission": {
      // Access policy is separate from connection state. The mock
      // records non-secret policy data on the entity record.
      if (!byId[change.agentId]) {
        return { ok: false, reason: `changePermission: unknown agent "${change.agentId}"` };
      }
      const agentsNext = agents.map((a) => {
        if (a.id !== change.agentId) return a;
        return { ...a, permissions: { ...(a.permissions || {}), [change.scope]: change.allowed } };
      });
      return { ok: true, agents: agentsNext, connections };
    }
    // ---- Skill 07: navigation / page manifest ops ----
    case "addNavItem": {
      if (!manifest) {
        return { ok: false, reason: "addNavItem: base.manifest was not provided" };
      }
      const seen = { ids: new Set(), routes: new Set() };
      for (const it of manifest.items || []) {
        if (it && it.id) seen.ids.add(it.id);
        if (it && it.route) seen.routes.add(it.route);
      }
      const check = validateNavItem(change.item, seen);
      if (!check.ok) {
        return { ok: false, reason: `addNavItem: ${check.errors.join("; ")}` };
      }
      return { ok: true, manifest: { ...manifest, items: [...manifest.items, change.item] } };
    }
    case "moveNav": {
      if (!manifest) {
        return { ok: false, reason: "moveNav: base.manifest was not provided" };
      }
      const sorted = [...(manifest.items || [])].sort((a, b) => a.order - b.order);
      const i = sorted.findIndex((it) => it && it.id === change.navId);
      if (i < 0) return { ok: false, reason: `moveNav: unknown nav item "${change.navId}"` };
      const j = i + change.delta;
      if (j < 0 || j >= sorted.length) {
        return {
          ok: false,
          reason: `moveNav: "${change.navId}" is already at the ${change.delta < 0 ? "start" : "end"}`,
        };
      }
      const a = sorted[i];
      const b = sorted[j];
      const next = [...manifest.items];
      const ia = next.indexOf(a);
      const ib = next.indexOf(b);
      if (a.order === b.order) {
        // Equal orders: shift the moving item past its neighbour
        // so the swap is observable (orders are plain numbers).
        next[ia] = { ...a, order: a.order + (change.delta > 0 ? 0.5 : -0.5) };
      } else {
        next[ia] = { ...a, order: b.order };
        next[ib] = { ...b, order: a.order };
      }
      return { ok: true, manifest: { ...manifest, items: next } };
    }
    case "setNavVisibility": {
      if (!manifest) {
        return { ok: false, reason: "setNavVisibility: base.manifest was not provided" };
      }
      const item = (manifest.items || []).find((it) => it && it.id === change.navId);
      if (!item) {
        return { ok: false, reason: `setNavVisibility: unknown nav item "${change.navId}"` };
      }
      // Visibility is a UI flag only — the manifest entry (its
      // data) is never deleted.
      return {
        ok: true,
        manifest: {
          ...manifest,
          items: manifest.items.map((it) =>
            it === item ? { ...it, visible: change.visible } : it
          ),
        },
      };
    }
    case "addPage": {
      if (!pages) {
        return { ok: false, reason: "addPage: base.pages was not provided" };
      }
      const check = validatePages([...pages, change.page]);
      if (!check.ok) {
        return { ok: false, reason: `addPage: ${check.errors.join("; ")}` };
      }
      return { ok: true, pages: [...pages, change.page] };
    }
    default:
      return { ok: false, reason: `unsupported draft op: ${String(change.op)}` };
  }
}

/**
 * Run a changeSet sequentially: each accepted op mutates the
 * working state, so later ops see earlier accepted ops. Rejected
 * ops are skipped (with their reason) and never mutate state.
 * Pure — the base state is never modified.
 */
function runChangeSet(registry, plan, changeSet) {
  const { base, changes } = changeSet || {};
  if (
    !base ||
    !Array.isArray(base.agents) ||
    !Array.isArray(base.connections) ||
    !Array.isArray(changes)
  ) {
    return {
      ok: false,
      error: {
        type: "invalid_change_set",
        message: "changeSet must include base.agents, base.connections and a changes array",
      },
    };
  }

  const pending = changes.filter((c) => c && c.status === "pending");
  let agents = [...base.agents];
  let connections = [...base.connections];
  // Navigation / page configuration (skill 07). Absent base means
  // nav ops are rejected with a readable reason — they can never
  // silently clobber configuration the caller did not provide.
  let manifest = base.manifest != null ? base.manifest : null;
  let pages = base.pages != null ? base.pages : null;
  const results = [];
  let rejected = 0;

  for (const change of pending) {
    // Scripted failures make partial-failure behavior testable
    // deterministically (skill 08: "simulated apply with partial
    // failure for testing").
    const scripted = plan[change.opId];
    if (scripted) {
      rejected += 1;
      results.push({ opId: change.opId, op: change.op, status: "rejected", reason: scripted });
      continue;
    }
    const outcome = applyOne(registry, agents, connections, change, manifest, pages);
    if (outcome.ok) {
      agents = outcome.agents ?? agents;
      connections = outcome.connections ?? connections;
      manifest = outcome.manifest ?? manifest;
      pages = outcome.pages ?? pages;
      results.push({ opId: change.opId, op: change.op, status: "accepted", reason: null });
    } else {
      rejected += 1;
      results.push({ opId: change.opId, op: change.op, status: "rejected", reason: outcome.reason });
    }
  }

  const status =
    pending.length === 0
      ? "noop"
      : rejected === 0
        ? "ok"
        : rejected === pending.length
          ? "failed"
          : "partial";

  return { ok: true, status, results, agents, connections, manifest, pages };
}

/**
 * createMockAdapter — the MOCK implementation of the adapter
 * contract. Deterministic data, labeled MOCK in every response.
 *
 * Options:
 *   registry    entity registry (kinds drive port compatibility)
 *   now         clock for result metadata (deterministic in tests)
 *   failurePlan { opId: reason } — scripted rejections for
 *               deterministic partial-failure testing
 */
export function createMockAdapter({
  registry,
  now,
  failurePlan,
  memory,
  navCapabilities = DEFAULT_NAV_CAPABILITIES,
} = {}) {
  const clock = now || (() => new Date().toISOString());
  const plan = failurePlan || {};
  // Workspace index for listResources/getResource. The app keeps
  // it in sync via syncWorkspace(); the mock holds no secrets.
  let workspace = null;

  return {
    label: "mock",
    simulated: true,

    getCapabilities() {
      return {
        label: "mock",
        simulated: true,
        schemaVersion: ADAPTER_SCHEMA_VERSION,
        // Workspace feature gates this provider can back (skill 08
        // acceptance: a second adapter with a different list
        // changes UI gating without component changes).
        navCapabilities: [...navCapabilities],
        capabilities: {
          applyChanges: CAPABILITY(true),
          validateChanges: CAPABILITY(true),
          listResources: CAPABILITY(true),
          getResource: CAPABILITY(true),
          getExecutionSnapshot: CAPABILITY(
            false,
            "execution snapshots are not part of the mock data model"
          ),
          subscribeEvents: CAPABILITY(
            false,
            "event streams arrive with the scripted mock of skill 06 (deferred)"
          ),
          requestAction: CAPABILITY(
            false,
            "the mock exposes no actionable commands"
          ),
          queryMemory: memory
            ? CAPABILITY(true)
            : CAPABILITY(
                false,
                "no shared-memory provider configured (skill 05)"
              ),
        },
      };
    },

    /** Keep the adapter's resource index in sync with the app state. */
    syncWorkspace(base) {
      workspace = base;
    },

    async listResources(kind, query = {}) {
      if (!RESOURCE_KINDS.includes(kind)) {
        return {
          ok: false,
          error: { type: "unsupported_kind", message: `unknown resource kind: ${String(kind)}` },
        };
      }
      const base = workspace || { agents: [], connections: [] };
      const pool = kind === "agent" ? base.agents : base.connections;
      const text = String(query.text || "").toLowerCase();
      const items = text
        ? pool.filter(
            (i) =>
              i.id.toLowerCase().includes(text) ||
              String(i.name || "").toLowerCase().includes(text)
          )
        : pool;
      const offset = Math.max(0, query.offset || 0);
      const limit = Math.max(1, query.limit || 50);
      return {
        ok: true,
        label: "mock",
        simulated: true,
        items: items.slice(offset, offset + limit),
        total: items.length,
        offset,
        limit,
      };
    },

    async getResource(kind, id) {
      if (!RESOURCE_KINDS.includes(kind)) {
        return {
          ok: false,
          error: { type: "unsupported_kind", message: `unknown resource kind: ${String(kind)}` },
        };
      }
      const base = workspace || { agents: [], connections: [] };
      const pool = kind === "agent" ? base.agents : base.connections;
      const found = pool.find((i) => i.id === id);
      if (!found) {
        return { ok: false, error: { type: "not_found", message: `${kind} "${id}" not found` } };
      }
      return { ok: true, label: "mock", simulated: true, item: found };
    },

    /** Dry run: per-operation validation results, no state returned. */
    async validateChanges(changeSet) {
      const run = runChangeSet(registry, plan, changeSet);
      if (!run.ok) return { ok: false, error: run.error };
      return {
        ok: true,
        label: "mock",
        simulated: true,
        schemaVersion: ADAPTER_SCHEMA_VERSION,
        status: run.status,
        results: run.results,
      };
    },

    /**
     * Apply a changeSet. MOCK — simulated, deterministic.
     * Returns per-operation results and the new state containing
     * ONLY the accepted operations. Never throws.
     */
    async applyChanges(changeSet) {
      const run = runChangeSet(registry, plan, changeSet);
      if (!run.ok) return { ok: false, error: run.error };
      return {
        ok: true,
        label: "mock",
        simulated: true,
        schemaVersion: ADAPTER_SCHEMA_VERSION,
        status: run.status,
        results: run.results,
        agents: run.agents,
        connections: run.connections,
        manifest: run.manifest,
        pages: run.pages,
        appliedAt: clock(),
      };
    },

    /**
     * Shared-memory retrieval (skill 05). Three separate
     * facts, checked in order:
     *   1. available   an enabled memory-read connection
     *   2. authorized  a policy grant for (agentId, scope)
     *   3. retrieval   the mock provider returns MOCK items
     * Read-only: no write path exists. Never throws.
     */
    async queryMemory(request) {
      if (!memory) {
        return unsupported(
          "queryMemory: no shared-memory provider configured"
        );
      }
      const agentId = request && request.agentId;
      const scope = request && request.scope;
      if (typeof agentId !== "string" || !agentId) {
        return {
          ok: false,
          error: {
            type: "invalid_request",
            message: "queryMemory requires a non-empty agentId",
          },
        };
      }
      if (typeof scope !== "string" || !scope) {
        return {
          ok: false,
          error: {
            type: "invalid_request",
            message: "queryMemory requires a non-empty scope",
          },
        };
      }
      const base = workspace || { agents: [], connections: [] };
      const memoryId = Object.values(registry.byId).find(
        (e) => e.kind === "memory"
      )?.id;
      const available =
        !!memoryId &&
        (base.connections || []).some(
          (c) =>
            c.from === agentId &&
            c.to === memoryId &&
            c.type === "memory-read" &&
            c.state !== "disabled"
        );
      if (!available) {
        return {
          ok: false,
          error: {
            type: "not_configured",
            message: `no enabled memory-read connection from "${agentId}" to the shared-memory node`,
          },
        };
      }
      if (!hasReadAccess(memory.policy, agentId, scope)) {
        return {
          ok: false,
          error: {
            type: "access_denied",
            message: `access denied: "${agentId}" has no read grant for scope "${scope}" (access is per agent and per scope)`,
          },
        };
      }
      return memory.provider.query({
        agentId,
        scope,
        text: (request && request.text) || "",
      });
    },

    // Declared unsupported in getCapabilities — calling them
    // returns typed errors instead of throwing.
    async getExecutionSnapshot(scope) {
      return unsupported(`getExecutionSnapshot is not supported by the mock (scope: ${String(scope)})`);
    },
    async subscribeEvents(scope, handler) {
      return unsupported(`subscribeEvents is not supported by the mock (scope: ${String(scope)})`);
    },
    async requestAction(action) {
      return unsupported(`requestAction is not supported by the mock (action: ${String(action)})`);
    },
  };
}
