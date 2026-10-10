// Draft change set + bounded undo/redo history (pure).
//
// The draft holds OPERATIONAL changes only (add/remove registration,
// add/remove connection, connection state, permissions). View changes
// (positions, fiber geometry) are NOT draft changes and are never
// proposed to a backend.
//
// Undo/redo applies to draft + view snapshots. Undo must NEVER be
// described as reverting a completed backend operation.

export const DRAFT_HISTORY_LIMIT = 100;

export const DRAFT_OPS = [
  "addEntity",
  "removeEntity",
  "addConnection",
  "removeConnection",
  "setConnectionState",
  "changePermission",
  // Skill 07: navigation / page manifest ops. These are local
  // workspace configuration — applied through the same
  // draft → validate → apply → persist flow (skill 04 rules).
  "addNavItem",
  "moveNav",
  "setNavVisibility",
  "addPage",
];

let opCounter = 0;
function nextOpId() {
  opCounter += 1;
  return `op-${opCounter.toString(36)}-${Date.now().toString(36)}`;
}

const PAYLOAD_CHECKS = {
  addEntity: (c) => !!c.entity && typeof c.entity.id === "string",
  removeEntity: (c) => typeof c.entityId === "string",
  addConnection: (c) => !!c.connection && typeof c.connection.id === "string",
  removeConnection: (c) => typeof c.connectionId === "string",
  setConnectionState: (c) =>
    typeof c.connectionId === "string" && ["enabled", "disabled"].includes(c.state),
  changePermission: (c) =>
    typeof c.agentId === "string" && typeof c.scope === "string" && typeof c.allowed === "boolean",
  addNavItem: (c) => !!c.item && typeof c.item.id === "string",
  moveNav: (c) => typeof c.navId === "string" && (c.delta === 1 || c.delta === -1),
  setNavVisibility: (c) =>
    typeof c.navId === "string" && typeof c.visible === "boolean",
  addPage: (c) => !!c.page && typeof c.page.id === "string",
};

export function createDraft() {
  return { changes: [] };
}

/**
 * Append a validated change to the draft. Pure.
 * A change carries: { op, ...payload } and gets { opId, status: "pending" }.
 * After a (simulated) apply, apply results update per-op status to
 * "accepted" / "rejected" with a reason (see applyResultsToDraft).
 */
export function addChange(draft, change) {
  const errors = [];
  if (!change || !DRAFT_OPS.includes(change.op)) {
    errors.push(`unknown draft op: ${String(change && change.op)}`);
  }
  const check = PAYLOAD_CHECKS[change && change.op];
  if (check && !check(change)) {
    errors.push(`invalid payload for op: ${String(change && change.op)}`);
  }
  if (errors.length) return { draft, added: false, errors };
  const entry = { opId: nextOpId(), status: "pending", ...change };
  return { draft: { changes: [...draft.changes, entry] }, added: true, errors: [] };
}

export function removeChange(draft, opId) {
  return { draft: { changes: draft.changes.filter((c) => c.opId !== opId) } };
}

export function discardDraft() {
  return createDraft();
}

/**
 * Record per-operation apply results on the draft (accepted / rejected
 * / partial). Rejected items stay in the draft WITH their reason.
 * results: [{ opId, status: "accepted"|"rejected", reason? }]
 */
export function applyResultsToDraft(draft, results) {
  const byOpId = new Map(results.map((r) => [r.opId, r]));
  return {
    draft: {
      changes: draft.changes.map((c) => {
        const r = byOpId.get(c.opId);
        if (!r) return c;
        return { ...c, status: r.status, reason: r.reason || null };
      }),
    },
  };
}

/** Readable pre-apply summary. Layout-only changes are listed separately. */
export function summarizeDraft(draft, viewChanges = []) {
  const pick = (op, key) =>
    draft.changes.filter((c) => c.op === op && c.status === "pending").map((c) => c[key]);
  return {
    addedEntities: pick("addEntity", "entity"),
    removedEntities: pick("removeEntity", "entityId"),
    addedConnections: pick("addConnection", "connection"),
    removedConnections: pick("removeConnection", "connectionId"),
    changedConnectionStates: draft.changes
      .filter((c) => c.op === "setConnectionState" && c.status === "pending")
      .map((c) => ({ connectionId: c.connectionId, state: c.state })),
    changedPermissions: draft.changes
      .filter((c) => c.op === "changePermission" && c.status === "pending")
      .map((c) => ({ agentId: c.agentId, scope: c.scope, allowed: c.allowed })),
    addedNavItems: pick("addNavItem", "item"),
    movedNavItems: draft.changes
      .filter((c) => c.op === "moveNav" && c.status === "pending")
      .map((c) => ({ navId: c.navId, delta: c.delta })),
    navVisibility: draft.changes
      .filter((c) => c.op === "setNavVisibility" && c.status === "pending")
      .map((c) => ({ navId: c.navId, visible: c.visible })),
    addedPages: pick("addPage", "page"),
    // Rejected operations stay in the draft WITH their
    // reason (spec: "After a rejected operation, the draft
    // keeps the rejected item with its reason").
    rejectedChanges: draft.changes
      .filter((c) => c.status === "rejected")
      .map((c) => ({ opId: c.opId, op: c.op, reason: c.reason })),
    layoutOnly: viewChanges,
    total: draft.changes.filter((c) => c.status === "pending").length,
  };
}

// ---- Bounded snapshot history for undo/redo of { draft, view } ----

export function createHistory(limit = DRAFT_HISTORY_LIMIT) {
  return { past: [], future: [], limit };
}

/** Push a snapshot; clears the redo branch. Bounded to `limit`. */
export function commit(history, snapshot) {
  return {
    ...history,
    past: [...history.past, snapshot].slice(-history.limit),
    future: [],
  };
}

/**
 * Undo one step. Returns { history, snapshot } where snapshot is the
 * restored previous state, or null when there is nothing to undo.
 * `current` is the live state to push onto the redo branch.
 */
export function undo(history, current) {
  if (history.past.length === 0) return { history, snapshot: null };
  const past = [...history.past];
  const snapshot = past.pop();
  return {
    history: { ...history, past, future: [current, ...history.future].slice(0, history.limit) },
    snapshot,
  };
}

/** Redo one step. Returns { history, snapshot } or null snapshot. */
export function redo(history, current) {
  if (history.future.length === 0) return { history, snapshot: null };
  const [snapshot, ...future] = history.future;
  return {
    history: { ...history, past: [...history.past, current].slice(-history.limit), future },
    snapshot,
  };
}
