// Configured connections model (pure).
//
// One fiber bundle == ONE logical configured connection.
// Ports have stable ids and a kind: control | tool-access | memory-read | memory-write.
// Compatibility is defined by the explicit PORT_RULES table, never by ad hoc
// checks in the renderer.

export const CONNECTION_TYPES = ["control", "tool-access", "memory-read", "memory-write"];

/**
 * Explicit port compatibility table.
 * A connection of `type` is allowed FROM an entity whose kind lists `type`
 * in `out`, TO an entity whose kind lists `type` in `in`.
 *
 * - orchestrator: can control agents, grant tool access, read/write memory.
 * - agent: accepts control; can access tools and read memory.
 * - tool: accepts control and tool-access; can relay tool-access onward
 *   (this is what makes the baseline docker -> wordpress relay valid).
 * - memory: accepts read/write only (a memory node never initiates).
 */
export const PORT_RULES = {
  orchestrator: { in: [], out: ["control", "tool-access", "memory-read", "memory-write"] },
  agent: { in: ["control", "memory-read"], out: ["tool-access", "memory-read"] },
  tool: { in: ["control", "tool-access"], out: ["tool-access"] },
  memory: { in: ["memory-read", "memory-write"], out: [] },
};

/**
 * Explicit cycle policy per connection type (NOT a blanket ban):
 * - control / tool-access / memory-write: cycles REJECTED (control loops and
 *   write loops are unsafe).
 * - memory-read: cycles PERMITTED (read-only, harmless).
 */
export const ACYCLIC_TYPES = ["control", "tool-access", "memory-write"];

/** Stable connection id derived from its endpoints and type. */
export function connectionId(from, type, to) {
  return `conn-${from}-${type}-${to}`;
}

/** Stable port id: "<entityId>:<direction>:<type>". */
export function portId(entityId, direction, type) {
  return `${entityId}:${direction}:${type}`;
}

/** List the ports an entity exposes, per the compatibility table. */
export function listPorts(registry, entityId) {
  const entity = registry.byId[entityId];
  if (!entity) return [];
  const rules = PORT_RULES[entity.kind];
  const ports = [];
  for (const type of rules.in) {
    ports.push({ id: portId(entityId, "in", type), entityId, direction: "in", type });
  }
  for (const type of rules.out) {
    ports.push({ id: portId(entityId, "out", type), entityId, direction: "out", type });
  }
  return ports;
}

/** Same source, same target, same type -> duplicate. Different type is allowed. */
export function isDuplicate(connections, { from, type, to }) {
  return connections.some((c) => c.from === from && c.to === to && c.type === type);
}

/**
 * Would adding from->to of `type` create a cycle? Only checked for acyclic
 * types. Follows enabled edges of the SAME type.
 */
export function wouldCreateCycle(connections, from, to, type) {
  if (!ACYCLIC_TYPES.includes(type)) return false;
  const adj = new Map();
  for (const c of connections) {
    if (c.type !== type || c.state === "disabled") continue;
    if (!adj.has(c.from)) adj.set(c.from, []);
    adj.get(c.from).push(c.to);
  }
  const stack = [to];
  const seen = new Set();
  while (stack.length) {
    const cur = stack.pop();
    if (cur === from) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const next of adj.get(cur) || []) stack.push(next);
  }
  return false;
}

/**
 * Full compatibility check for a proposed connection.
 * @returns {{ok:boolean, reason:string|null}}
 */
export function canConnect(registry, connections, { from, to, type }) {
  const src = registry.byId[from];
  const dst = registry.byId[to];
  if (!src) return { ok: false, reason: `unknown source: ${from}` };
  if (!dst) return { ok: false, reason: `unknown target: ${to}` };
  if (from === to) return { ok: false, reason: "self-connections are rejected" };
  if (!CONNECTION_TYPES.includes(type)) return { ok: false, reason: `unknown connection type: ${type}` };
  if (!PORT_RULES[src.kind].out.includes(type)) {
    return { ok: false, reason: `a "${src.kind}" cannot output "${type}"` };
  }
  if (!PORT_RULES[dst.kind].in.includes(type)) {
    return { ok: false, reason: `a "${dst.kind}" cannot accept "${type}"` };
  }
  if (isDuplicate(connections, { from, type, to })) {
    return { ok: false, reason: "duplicate connection (same source, target and type)" };
  }
  if (wouldCreateCycle(connections, from, to, type)) {
    return { ok: false, reason: `"${type}" connections must not create cycles` };
  }
  return { ok: true, reason: null };
}

/** Validate and build one connection. Pure. */
export function createConnection(registry, connections, { from, to, type, scope = [] }) {
  const check = canConnect(registry, connections, { from, to, type });
  if (!check.ok) return { connection: null, errors: [check.reason] };
  return {
    connection: { id: connectionId(from, type, to), from, to, type, state: "enabled", scope: [...scope] },
    errors: [],
  };
}

export function validateConnection(registry, connections, conn) {
  return canConnect(registry, connections, conn);
}

/** Build a connection list from specs, skipping invalid ones and reporting them. */
export function createConnections(registry, specs = []) {
  const list = [];
  const errors = [];
  for (const spec of specs) {
    const { connection, errors: errs } = createConnection(registry, list, spec);
    if (connection) list.push(connection);
    else errors.push(...errs);
  }
  return { list, errors };
}

/**
 * All connection types that are valid between two nodes right now.
 * Pure. `excludeId` removes a connection from the duplicate check —
 * used while reconnecting that very connection.
 */
export function compatibleTypes(registry, connections, { from, to }, excludeId = null) {
  const pool = excludeId ? connections.filter((c) => c.id !== excludeId) : connections;
  return CONNECTION_TYPES.filter((type) =>
    canConnect(registry, pool, { from, to, type }).ok
  );
}
