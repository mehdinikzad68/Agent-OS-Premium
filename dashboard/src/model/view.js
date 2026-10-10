// View configuration model (pure).
//
// View state is NEVER operational configuration: node positions, fiber
// control points, grouping, visibility, saved views and the viewport live
// here. It is persisted locally and is never sent to a backend as a
// "change". Registered entities and configured connections are separate
// models (registry.js / connections.js).

export const VIEW_SCHEMA_VERSION = 1;

const isNum = (n) => typeof n === "number" && Number.isFinite(n);

/** Default (empty) view state. Positions are computed by the layout engine
 * until the user arranges them manually. */
export function createDefaultView() {
  return {
    schemaVersion: VIEW_SCHEMA_VERSION,
    positions: {}, // entityId -> { x, y, locked }
    fiberGeometry: {}, // connectionId -> { midpoint: {x, y} | null }
    groups: {}, // groupId -> { label, memberIds: string[], collapsed }
    hidden: [], // entityIds hidden from THIS view (still registered)
    savedViews: [], // [{ id, name, view }]
    viewport: { zoom: 1, panX: 0, panY: 0 },
  };
}

/** Structural validation. Reports every problem, does not throw. */
export function validateViewState(view) {
  const errors = [];
  if (!view || typeof view !== "object") return { ok: false, errors: ["view must be an object"] };
  if (view.schemaVersion !== VIEW_SCHEMA_VERSION) {
    errors.push(`unsupported schemaVersion: ${String(view.schemaVersion)}`);
  }
  for (const [id, p] of Object.entries(view.positions || {})) {
    if (!p || !isNum(p.x) || !isNum(p.y)) errors.push(`position "${id}": x and y must be finite numbers`);
    else if (p.locked != null && typeof p.locked !== "boolean") errors.push(`position "${id}": locked must be a boolean`);
  }
  for (const [cid, g] of Object.entries(view.fiberGeometry || {})) {
    if (!g) errors.push(`fiberGeometry "${cid}": must be an object`);
    else if (g.midpoint != null && (!isNum(g.midpoint.x) || !isNum(g.midpoint.y))) {
      errors.push(`fiberGeometry "${cid}": midpoint must be {x, y}`);
    }
  }
  for (const [gid, g] of Object.entries(view.groups || {})) {
    if (!g || !Array.isArray(g.memberIds) || !g.memberIds.every((m) => typeof m === "string")) {
      errors.push(`group "${gid}": memberIds must be an array of ids`);
    } else if (g.collapsed != null && typeof g.collapsed !== "boolean") {
      errors.push(`group "${gid}": collapsed must be a boolean`);
    }
  }
  if (view.hidden != null && (!Array.isArray(view.hidden) || !view.hidden.every((h) => typeof h === "string"))) {
    errors.push("hidden must be an array of entity ids");
  }
  if (view.savedViews != null && !Array.isArray(view.savedViews)) errors.push("savedViews must be an array");
  const vp = view.viewport;
  if (!vp || !isNum(vp.zoom) || !isNum(vp.panX) || !isNum(vp.panY)) {
    errors.push("viewport must contain finite numeric zoom/panX/panY");
  }
  return { ok: errors.length === 0, errors };
}

/**
 * Graceful recovery: keep every valid section, drop malformed sections with a
 * readable error, never crash. Always returns a usable view.
 */
export function sanitizeViewState(view) {
  const clean = createDefaultView();
  const errors = [];
  if (!view || typeof view !== "object") {
    return { view: clean, errors: ["view state is not an object; defaults restored"] };
  }
  if (view.schemaVersion === VIEW_SCHEMA_VERSION) {
    clean.schemaVersion = VIEW_SCHEMA_VERSION;
  } else {
    errors.push(`unsupported schemaVersion ${String(view.schemaVersion)}; defaults restored`);
  }
  for (const [id, p] of Object.entries(view.positions || {})) {
    if (p && isNum(p.x) && isNum(p.y)) {
      clean.positions[id] = { x: p.x, y: p.y, locked: p.locked === true };
    } else {
      errors.push(`position "${id}" is malformed; ignored`);
    }
  }
  for (const [cid, g] of Object.entries(view.fiberGeometry || {})) {
    if (g && (g.midpoint == null || (isNum(g.midpoint.x) && isNum(g.midpoint.y)))) {
      clean.fiberGeometry[cid] = { midpoint: g.midpoint || null };
    } else {
      errors.push(`fiber geometry "${cid}" is malformed; ignored`);
    }
  }
  for (const [gid, g] of Object.entries(view.groups || {})) {
    if (g && Array.isArray(g.memberIds) && g.memberIds.every((m) => typeof m === "string")) {
      clean.groups[gid] = {
        label: typeof g.label === "string" ? g.label : gid,
        memberIds: [...g.memberIds],
        collapsed: g.collapsed === true,
      };
    } else {
      errors.push(`group "${gid}" is malformed; ignored`);
    }
  }
  if (Array.isArray(view.hidden) && view.hidden.every((h) => typeof h === "string")) {
    clean.hidden = [...view.hidden];
  } else if (view.hidden != null) {
    errors.push("hidden is malformed; ignored");
  }
  if (Array.isArray(view.savedViews)) {
    clean.savedViews = view.savedViews.filter(
      (v) => v && typeof v.id === "string" && typeof v.name === "string" && v.view && typeof v.view === "object"
    );
  } else if (view.savedViews != null) {
    errors.push("savedViews is malformed; ignored");
  }
  const vp = view.viewport;
  if (vp && isNum(vp.zoom) && isNum(vp.panX) && isNum(vp.panY)) {
    clean.viewport = { zoom: vp.zoom, panX: vp.panX, panY: vp.panY };
  } else {
    errors.push("viewport is malformed; defaults restored");
  }
  return { view: clean, errors };
}

// ---- Pure updaters (always return a new view) ----

export function setPosition(view, id, x, y) {
  return { ...view, positions: { ...view.positions, [id]: { ...view.positions[id], x, y } } };
}

export function setLocked(view, id, locked) {
  const prev = view.positions[id] || { x: 0, y: 0 };
  return { ...view, positions: { ...view.positions, [id]: { ...prev, locked: locked === true } } };
}

export function setHidden(view, id, hidden) {
  const set = new Set(view.hidden);
  if (hidden) set.add(id);
  else set.delete(id);
  return { ...view, hidden: [...set] };
}

export function setFiberMidpoint(view, connectionId, midpoint) {
  return { ...view, fiberGeometry: { ...view.fiberGeometry, [connectionId]: { midpoint: midpoint || null } } };
}

export function setGroup(view, groupId, { label, memberIds = [], collapsed = false }) {
  return {
    ...view,
    groups: { ...view.groups, [groupId]: { label, memberIds: [...memberIds], collapsed: collapsed === true } },
  };
}

export function setViewport(view, viewport) {
  return { ...view, viewport: { ...view.viewport, ...viewport } };
}

export function saveNamedView(view, id, name) {
  const snapshot = {
    positions: view.positions,
    fiberGeometry: view.fiberGeometry,
    groups: view.groups,
    hidden: view.hidden,
    viewport: view.viewport,
  };
  const others = view.savedViews.filter((v) => v.id !== id);
  return { ...view, savedViews: [...others, { id, name, view: snapshot }] };
}

/**
 * Reset LAYOUT only: clears manual positions, fiber geometry and the viewport.
 * Registered entities, connections, groups, hidden flags and saved views are
 * untouched. Distinct from any system/configuration reset.
 */
export function resetLayout(view) {
  return {
    ...view,
    positions: {},
    fiberGeometry: {},
    viewport: { zoom: 1, panX: 0, panY: 0 },
  };
}

// ---- World <-> screen coordinates (direction-agnostic; works in RTL and LTR) ----

export function worldToScreen(view, p) {
  const { zoom, panX, panY } = view.viewport;
  return { x: p.x * zoom + panX, y: p.y * zoom + panY };
}

export function screenToWorld(view, p) {
  const { zoom, panX, panY } = view.viewport;
  return { x: (p.x - panX) / zoom, y: (p.y - panY) / zoom };
}
