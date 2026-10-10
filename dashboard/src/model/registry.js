// Registered entities model (pure: no React, no DOM, no backend logic).
//
// Kinds: orchestrator | agent | tool | memory.
// The coordinator identity is a ROLE (kind "orchestrator"), not a hardcoded
// id. The baseline demo keeps "Hermes" as the default example.

export const SCHEMA_VERSION = 1;

export const ENTITY_KINDS = ["orchestrator", "agent", "tool", "memory"];

// Stable ids: letters/digits/underscore/dash, 1-64 chars, must start alphanumeric.
export const ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

/**
 * @typedef {Object} RegisteredEntity
 * @property {string} id        Stable unique id.
 * @property {"orchestrator"|"agent"|"tool"|"memory"} kind
 * @property {string} name      Display name.
 * @property {{en:string, fa:string}} [description] Localized description.
 * @property {string} [role]    Role slug (e.g. "code-agent").
 * @property {string[]} [capabilities]
 * @property {string} [icon]    Icon identifier from the manifest allowlist.
 * @property {string} [provider] Memory provider (e.g. "obsidian"). Required for kind "memory".
 * @property {string[]} [scopes] Allowed resource scopes.
 * @property {string|null} [parent] Relay parent id (used by the demo UI for grouped tools).
 * @property {boolean} [custom] True for user-created entities.
 * // Demo display fields, preserved verbatim from the baseline artifact:
 * @property {string} [status] running|awaiting|complete|offline
 * @property {string} [tok] Demo token count (DEMO label applies).
 * @property {number} [load] Demo load percentage (DEMO label applies).
 * @property {string} [seen] Demo last-seen time.
 * @property {string} [cmd] Demo command tag.
 */

/**
 * Validate one entity against the registry rules.
 * @param {RegisteredEntity} entity
 * @param {{byId?: Object, hasOrchestrator?: boolean}} existing
 * @returns {{ok:boolean, errors:string[]}}
 */
export function validateEntity(entity, existing = {}) {
  const errors = [];
  if (!entity || typeof entity !== "object") {
    return { ok: false, errors: ["entity must be an object"] };
  }
  if (typeof entity.id !== "string" || !ID_PATTERN.test(entity.id)) {
    errors.push("id must be a stable string (alphanumeric, _ or -, 1-64 chars, starting alphanumeric)");
  }
  if (!ENTITY_KINDS.includes(entity.kind)) {
    errors.push(`kind must be one of: ${ENTITY_KINDS.join(", ")}`);
  }
  if (typeof entity.name !== "string" || entity.name.trim().length === 0) {
    errors.push("name must be a non-empty string");
  }
  if (entity.kind === "orchestrator" && existing.hasOrchestrator) {
    errors.push("the registry accepts exactly one orchestrator");
  }
  if (existing.byId && existing.byId[entity.id]) {
    errors.push(`duplicate id: ${entity.id}`);
  }
  if (entity.capabilities != null && !Array.isArray(entity.capabilities)) {
    errors.push("capabilities must be an array of strings when present");
  }
  if (entity.kind === "memory" && typeof entity.provider !== "string") {
    errors.push("memory entities require a provider field (e.g. \"obsidian\")");
  }
  if (entity.parent != null && typeof entity.parent !== "string") {
    errors.push("parent must be a string id or null");
  }
  if (entity.parent && existing.byId && !existing.byId[entity.parent]) {
    errors.push(`parent id is not registered: ${entity.parent}`);
  }
  return { ok: errors.length === 0, errors };
}

/**
 * Build a registry from a list of entities. Invalid entities are skipped and
 * reported; valid ones are kept (graceful, non-crashing behavior).
 * @param {RegisteredEntity[]} entities
 * @returns {{schemaVersion:number, byId:Object, errors:string[]}}
 */
export function createRegistry(entities = []) {
  const byId = {};
  let hasOrchestrator = false;
  const errors = [];
  for (const e of entities) {
    const res = validateEntity(e, { byId, hasOrchestrator });
    if (!res.ok) {
      errors.push(...res.errors);
      continue;
    }
    byId[e.id] = { ...e };
    if (e.kind === "orchestrator") hasOrchestrator = true;
  }
  return { schemaVersion: SCHEMA_VERSION, byId, errors };
}

/**
 * Pure add. Returns a new registry; the input is never mutated.
 */
export function addEntity(registry, entity) {
  const hasOrchestrator = Object.values(registry.byId).some((e) => e.kind === "orchestrator");
  const res = validateEntity(entity, { byId: registry.byId, hasOrchestrator });
  if (!res.ok) return { registry, added: false, errors: res.errors };
  return {
    registry: { ...registry, byId: { ...registry.byId, [entity.id]: { ...entity } } },
    added: true,
    errors: [],
  };
}

/**
 * Pure remove. The orchestrator cannot be unregistered.
 * Note: connections referencing the removed id become dangling; draft apply
 * (phase 4) is responsible for validating them.
 */
export function removeEntity(registry, id) {
  const entity = registry.byId[id];
  if (!entity) return { registry, removed: false, errors: [`unknown id: ${id}`] };
  if (entity.kind === "orchestrator") {
    return { registry, removed: false, errors: ["the orchestrator cannot be unregistered"] };
  }
  const { [id]: _removed, ...rest } = registry.byId;
  return { registry: { ...registry, byId: rest }, removed: true, errors: [] };
}

/** Coordinator lookup is by ROLE (kind), never by a hardcoded id. */
export function getCoordinator(registry) {
  return Object.values(registry.byId).find((e) => e.kind === "orchestrator") || null;
}

export function findEntity(registry, id) {
  return registry.byId[id] || null;
}

export function entitiesOfKind(registry, kind) {
  return Object.values(registry.byId).filter((e) => e.kind === kind);
}
