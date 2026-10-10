// Workspace persistence behind a provider-neutral storage
// interface (skill 04).
//
// The interface is all the app needs: read / write / remove
// of strings under a key. The localStorage implementation
// lives here; a future service (Agent OS backend, vault
// bridge) implements the same interface and replaces this
// module without touching the models.
//
// IMPORTANT: browser storage is LOCAL to this browser. It is
// not multi-user persistence and it is not a backup.
//
// Every stored record carries a schemaVersion and is
// validated on load. A malformed section keeps its default
// and reports a readable error — the app never crashes on
// bad stored data. Only non-secret configuration is stored:
// ids, names, kinds, states, positions. No credentials, no
// tokens, no private paths.

import { sanitizeViewState, VIEW_SCHEMA_VERSION } from "../model/view.js";
import { canConnect } from "../model/connections.js";
import { validateManifest, validatePages } from "../model/manifest.js";

export const WORKSPACE_SCHEMA_VERSION = 1;
export const WORKSPACE_KEY = "agentos-workspace-v1";
// Phase-2 scratch key (no schemaVersion) — migrated once.
export const LEGACY_TOOLS_KEY = "agentos-neural-tools-v1";

// ---- Storage interface ----

function defaultStorage() {
  try {
    return window.localStorage;
  } catch {
    return createMemoryStorage();
  }
}

/** In-memory storage with the localStorage shape — used as
 *  the fallback and by tests. */
export function createMemoryStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => void map.set(k, String(v)),
    removeItem: (k) => void map.delete(k),
  };
}

/** localStorage implementation of the storage interface.
 *  All operations are best-effort: failures (quota, private
 *  mode) return null/false instead of throwing. */
export function createLocalStorageAdapter(storage = defaultStorage()) {
  return {
    async read(key) {
      try {
        return storage.getItem(key);
      } catch {
        return null;
      }
    },
    async write(key, value) {
      try {
        storage.setItem(key, value);
        return true;
      } catch {
        return false;
      }
    },
    async remove(key) {
      try {
        storage.removeItem(key);
      } catch {}
    },
  };
}

// ---- Section validators (pure, report-and-recover) ----

const isStr = (v) => typeof v === "string" && v.length > 0;

// Mirrors the UI status vocabulary (scene/colors.js STATUS_COLOR keys).
const AGENT_STATUSES = ["running", "awaiting", "complete", "offline"];

/**
 * Custom tools are DISPLAY records, not registry entities: the renderer
 * reads `a.sub[lang]` and `STATUS_COLOR[a.status]` unconditionally, and the
 * status counters do `c[a.status]++`. A record that is valid JSON but lacks
 * those fields (hand-written import, older export) would therefore crash the
 * whole app (TypeError on `a.sub[lang]`) or produce NaN counters.
 *
 * Normalizing here — at the persistence boundary — keeps the fix in one
 * place instead of scattering null-guards through every renderer.
 */
function normalizeCustomTool(a) {
  const name = a.name;
  const sub =
    a.sub && typeof a.sub === "object"
      ? { en: isStr(a.sub.en) ? a.sub.en : name, fa: isStr(a.sub.fa) ? a.sub.fa : name }
      : { en: name, fa: name };
  return {
    ...a,
    sub,
    status: AGENT_STATUSES.includes(a.status) ? a.status : "offline",
    tok: typeof a.tok === "string" ? a.tok : "0",
    load: typeof a.load === "number" && Number.isFinite(a.load) ? a.load : 0,
    seen: isStr(a.seen) ? a.seen : "00:00",
    custom: true,
  };
}

function validateCustomTools(tools) {
  const clean = [];
  const errors = [];
  if (!Array.isArray(tools)) {
    return { clean, errors: ["customTools must be an array; defaults restored"] };
  }
  tools.forEach((a, i) => {
    if (a && isStr(a.id) && isStr(a.name)) {
      // Display fields are repaired silently: they carry safe defaults and
      // are not configuration. Only a missing id/name is fatal for a row.
      clean.push(normalizeCustomTool(a));
    } else {
      errors.push(`customTools[${i}] needs a non-empty id and name; ignored`);
    }
  });
  return { clean, errors };
}

function validateConnections(connections, byId) {
  const clean = [];
  const errors = [];
  if (!Array.isArray(connections)) {
    return { clean, errors: ["connections must be an array; defaults restored"] };
  }
  connections.forEach((c, i) => {
    const check = canConnect({ byId }, clean, c);
    if (check.ok) {
      clean.push({ ...c, state: c.state === "disabled" ? "disabled" : "enabled" });
    } else {
      errors.push(`connection[${i}] (${c && c.id}): ${check.reason}; ignored`);
    }
  });
  return { clean, errors };
}

function entityUniverse(registry, customTools) {
  const byId = {};
  for (const e of Object.values(registry.byId)) {
    byId[e.id] = { id: e.id, kind: e.kind };
  }
  for (const a of customTools) {
    if (!byId[a.id]) byId[a.id] = { id: a.id, kind: "tool" };
  }
  return byId;
}

/**
 * Validate and normalize every section of a workspace
 * record. `connections: null` (or absent) means "keep the
 * current defaults" — only a validated array replaces them.
 */
function validateSections(sections, registry) {
  const errors = [];

  const tools = validateCustomTools(sections.customTools);
  errors.push(...tools.errors);

  const byId = entityUniverse(registry, tools.clean);
  let connections = null;
  if (Array.isArray(sections.connections)) {
    const conns = validateConnections(sections.connections, byId);
    errors.push(...conns.errors);
    connections = conns.clean;
  } else if (sections.connections != null) {
    errors.push("connections is not an array; defaults restored");
  }

  let view = null;
  if (sections.view != null) {
    const sanitized = sanitizeViewState(sections.view);
    errors.push(...sanitized.errors);
    view = sanitized.view;
  }

  // Navigation manifest + standard pages (skill 07). A malformed
  // section keeps the built-in defaults and reports a readable
  // error — stored data never crashes the app.
  let manifest = null;
  if (sections.manifest != null) {
    if (sections.manifest && typeof sections.manifest === "object" && !Array.isArray(sections.manifest)) {
      const check = validateManifest(sections.manifest);
      if (check.ok) manifest = sections.manifest;
      else errors.push(`manifest: ${check.errors.join("; ")}; defaults restored`);
    } else {
      errors.push("manifest must be an object; defaults restored");
    }
  }

  let pages = null;
  if (sections.pages != null) {
    const check = validatePages(sections.pages);
    if (check.ok) pages = sections.pages;
    else errors.push(`pages: ${check.errors.join("; ")}; defaults restored`);
  }

  return { customTools: tools.clean, connections, view, manifest, pages, errors };
}

// ---- Load / save ----

/**
 * Load the workspace record. Returns
 *   { customTools, connections, view, errors }
 * where `connections`/`view` are null when the record
 * (or that section) is absent — the caller keeps its
 * defaults. Malformed data never throws.
 */
export async function loadWorkspace(storage, { registry } = {}) {
  const errors = [];
  let record = null;

  const raw = await storage.read(WORKSPACE_KEY);
  if (raw != null) {
    try {
      record = JSON.parse(raw);
    } catch (err) {
      errors.push(`workspace record is malformed JSON (${err.message}); defaults restored`);
    }
  } else {
    // One-time migration of the phase-2 scratch key
    // (records without schemaVersion).
    const legacyRaw = await storage.read(LEGACY_TOOLS_KEY);
    if (legacyRaw != null) {
      try {
        const legacy = JSON.parse(legacyRaw);
        if (Array.isArray(legacy)) {
          record = {
            schemaVersion: WORKSPACE_SCHEMA_VERSION,
            savedAt: null,
            sections: { customTools: legacy, connections: null, view: null },
          };
          await saveWorkspace(storage, {
            customTools: legacy,
            connections: null,
            view: null,
          });
          await storage.remove(LEGACY_TOOLS_KEY);
        } else {
          errors.push("legacy workspace data is not an array; defaults restored");
        }
      } catch (err) {
        errors.push(`legacy workspace data is malformed (${err.message}); defaults restored`);
      }
    }
  }

  if (!record) {
    return { customTools: [], connections: null, view: null, manifest: null, pages: null, errors };
  }
  if (!record || typeof record !== "object" || record.schemaVersion !== WORKSPACE_SCHEMA_VERSION) {
    errors.push(
      `unsupported workspace schemaVersion ${String(record && record.schemaVersion)}; defaults restored`
    );
    return { customTools: [], connections: null, view: null, manifest: null, pages: null, errors };
  }

  const sections = record.sections || {};
  const validated = validateSections(
    {
      customTools: sections.customTools,
      connections: sections.connections,
      view: sections.view,
      manifest: sections.manifest,
      pages: sections.pages,
    },
    registry
  );
  errors.push(...validated.errors);
  return validated;
}

/** Persist the workspace record. Best-effort: returns whether
 *  the write succeeded (quota / private mode may reject it). */
export async function saveWorkspace(storage, { customTools, connections, view, manifest, pages }) {
  const record = {
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    savedAt: new Date().toISOString(),
    sections: {
      customTools: customTools == null ? [] : customTools,
      // null means "keep defaults on next load"; [] means
      // "the user genuinely removed every connection".
      connections: connections == null ? null : connections,
      view: view == null ? null : view,
      manifest: manifest == null ? null : manifest,
      pages: pages == null ? null : pages,
    },
  };
  return storage.write(WORKSPACE_KEY, JSON.stringify(record));
}

// ---- Export / import ----

/**
 * Produce the export JSON. By construction it contains only
 * non-secret workspace configuration — no credentials, no
 * tokens, no private paths.
 */
export function exportWorkspace({ customTools, connections, view, manifest, pages }) {
  return JSON.stringify(
    {
      schemaVersion: WORKSPACE_SCHEMA_VERSION,
      exportedAt: new Date().toISOString(),
      label: "Agent-OS Neural Command workspace export (MOCK demo data)",
      sections: {
        customTools: customTools || [],
        connections: connections || [],
        view: view || null,
        manifest: manifest || null,
        pages: pages || null,
      },
    },
    null,
    2
  );
}

/**
 * Parse and validate an import file. Returns:
 *   { ok: false, errors }                     — fatal: not JSON / wrong schemaVersion
 *   { ok: true, workspace, errors }           — parseable; section-level errors
 *                                                are listed for the preview step
 * Never throws. The caller shows the preview (with errors)
 * BEFORE applying anything.
 */
export function parseImport(json, { registry } = {}) {
  let record = null;
  try {
    record = JSON.parse(json);
  } catch (err) {
    return { ok: false, errors: [`malformed JSON: ${err.message}`] };
  }
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    return { ok: false, errors: ["import must be a JSON object"] };
  }
  if (record.schemaVersion !== WORKSPACE_SCHEMA_VERSION) {
    return {
      ok: false,
      errors: [
        `unsupported schemaVersion ${String(record.schemaVersion)}; expected ${WORKSPACE_SCHEMA_VERSION}`,
      ],
    };
  }
  const sections = record.sections || {};
  const validated = validateSections(
    {
      customTools: sections.customTools,
      connections: sections.connections,
      view: sections.view,
      manifest: sections.manifest,
      pages: sections.pages,
    },
    registry
  );
  return { ok: true, workspace: validated, errors: validated.errors };
}
