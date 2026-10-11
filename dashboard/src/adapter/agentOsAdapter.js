// Real Agent OS adapter — implements the provider-neutral adapter contract
// (skill 08 / docs/adapter-contract.md) against the live control-service HTTP
// API, using the api() client in ./client.js.
//
// SCOPE (deliberate, honest): READ-ONLY.
//   The control-service exposes resources (missions, jobs, approvals,
//   projects, executors, events) that do NOT map onto the command-canvas
//   draft ops (addEntity / addConnection / ...). Those draft ops describe a
//   local workspace graph; the backend has no such concept. So this adapter
//   reports applyChanges / validateChanges as UNSUPPORTED with a clear
//   explanation rather than faking them. Writing to the backend (creating
//   missions/jobs, dispatching) is a deliberate future step that must go
//   through the approval gate — it is not silently wired here.
//
// Every method returns typed results ({ ok:false, error:{type,message} }) and
// never throws into the renderer (skill 08). The UI never builds URLs: all
// paths below are relative (/api/...), same-origin in production and proxied
// in dev.
//
// Data truthfulness: label is "agent-os", simulated is false. The UI must show
// these as LIVE data, distinct from the mock adapter's demo data.

import { api } from "../api/client.js";

export const AGENT_OS_ADAPTER_ID = "agent-os";

// Resource kinds this adapter can list/fetch, mapped to backend endpoints.
// The value is the collection key the backend wraps its responses in
// (e.g. GET /api/missions -> { missions: [...] }).
const RESOURCE_KINDS = {
  mission: { path: "/api/missions", collection: "missions", item: (id) => `/api/missions/${encodeURIComponent(id)}` },
  job: { path: "/api/jobs", collection: "jobs", item: (id) => `/api/jobs/${encodeURIComponent(id)}` },
  approval: { path: "/api/approvals", collection: "approvals", item: null },
  executor: { path: "/api/executors", collection: "executors", item: null },
  project: { path: "/api/projects", collection: "projects", item: (id) => `/api/projects/${encodeURIComponent(id)}` },
  event: { path: "/api/events", collection: "events", item: null },
};

export const AGENT_OS_RESOURCE_KINDS = Object.keys(RESOURCE_KINDS);

// Map an HTTP failure to the adapter's typed error taxonomy.
function mapHttpError(e) {
  const status = e && e.status;
  const message = (e && e.message) || "request failed";
  let type = "server_error";
  if (status == null) type = "network";
  else if (status === 401) type = "unauthorized";
  else if (status === 403) type = "forbidden";
  else if (status === 404) type = "not_found";
  else if (status === 400) type = "invalid_request";
  else if (status === 409) type = "conflict";
  else if (status >= 500) type = "server_error";
  return { ok: false, error: { type, message, status: status ?? null } };
}

const CAP = (supported, explanation = null) => ({
  supported,
  authorized: supported,
  available: supported,
  configured: supported,
  explanation,
});

/**
 * createAgentOsAdapter — a real, READ-ONLY adapter over the control-service.
 *
 * Options:
 *   getSnapshot   optional async () => string used only for tests/clock skew
 *                 checks; the real clock is not needed for reads.
 */
export function createAgentOsAdapter() {
  // Polling handle for subscribeEvents (the backend has no SSE/stream; it is
  // an append-only log you poll). We keep the timer here so unsubscribe can
  // clear it.
  let pollTimer = null;

  return {
    id: AGENT_OS_ADAPTER_ID,
    label: "agent-os",
    simulated: false,

    getCapabilities() {
      return {
        id: AGENT_OS_ADAPTER_ID,
        label: "agent-os",
        simulated: false,
        schemaVersion: 1,
        // Feature gates this provider backs. It does NOT back the command
        // canvas graph editing (that is local workspace config), so "canvas"
        // is intentionally absent — the sidebar entry for it stays on the
        // local/mock path.
        navCapabilities: ["timeline", "resource-tables", "schema-forms", "run-clusters"],
        capabilities: {
          // Reads are real.
          listResources: CAP(true),
          getResource: CAP(true),
          getExecutionSnapshot: CAP(true),
          subscribeEvents: CAP(true, "polling the append-only event log (no push stream)"),
          // Writes: the draft-ops model does not map to backend resources.
          // Reported unsupported rather than faked (skill 08 honesty).
          validateChanges: CAP(false, "the workspace draft-ops model has no backend equivalent yet"),
          applyChanges: CAP(false, "backend writes go through missions/jobs/approvals, not draft ops"),
          requestAction: CAP(false, "dispatch is gated by human approval; not wired from this adapter yet"),
          queryMemory: CAP(false, "the control-service exposes no shared-memory HTTP endpoint"),
        },
      };
    },

    // The backend owns its own state; there is no local workspace index to sync.
    syncWorkspace() {},

    async listResources(kind, query = {}) {
      const spec = RESOURCE_KINDS[kind];
      if (!spec) {
        return {
          ok: false,
          error: { type: "unsupported_kind", message: `unknown resource kind: ${String(kind)}` },
        };
      }
      let data;
      try {
        data = await api("GET", spec.path);
      } catch (e) {
        return mapHttpError(e);
      }
      // Executors come back as an array of strings, not objects; normalize so
      // the UI always gets { id, ... } rows.
      let items = data[spec.collection] || [];
      if (kind === "executor") {
        items = items.map((name) => ({ id: name, name }));
      }
      // Client-side text filter + paging (the backend returns full lists).
      const text = String(query.text || "").toLowerCase();
      const filtered = text
        ? items.filter((i) =>
            String(i.id || "").toLowerCase().includes(text) ||
            String(i.name || i.title || "").toLowerCase().includes(text)
          )
        : items;
      const offset = Math.max(0, query.offset || 0);
      const limit = Math.max(1, query.limit || 50);
      return {
        ok: true,
        label: "agent-os",
        simulated: false,
        items: filtered.slice(offset, offset + limit),
        total: filtered.length,
        offset,
        limit,
      };
    },

    async getResource(kind, id) {
      const spec = RESOURCE_KINDS[kind];
      if (!spec) {
        return {
          ok: false,
          error: { type: "unsupported_kind", message: `unknown resource kind: ${String(kind)}` },
        };
      }
      if (!spec.item) {
        return {
          ok: false,
          error: { type: "unsupported", message: `single-resource fetch is not exposed for "${kind}"` },
        };
      }
      try {
        const data = await api("GET", spec.item(id));
        return { ok: true, label: "agent-os", simulated: false, item: data };
      } catch (e) {
        return mapHttpError(e);
      }
    },

    /**
     * Runtime snapshot assembled from the real job list + event log. This is
     * what backs the "live" timeline data. Returns a shape the UI can use
     * without inventing run states the backend does not report.
     */
    async getExecutionSnapshot() {
      try {
        const [jobsData, eventsData] = await Promise.all([
          api("GET", "/api/jobs"),
          api("GET", "/api/events"),
        ]);
        return {
          ok: true,
          label: "agent-os",
          simulated: false,
          jobs: jobsData.jobs || [],
          events: eventsData.events || [],
          fetchedAt: new Date().toISOString(),
        };
      } catch (e) {
        return mapHttpError(e);
      }
    },

    /**
     * Poll the append-only event log. The backend has no push stream, so this
     * is honest polling: it fetches events and hands the caller any whose `seq`
     * is newer than the last seen. Returns an unsubscribe function.
     *
     * @param {object}   options        { intervalMs = 5000, onEvents, onError }
     * @returns {Function} unsubscribe  clears the timer.
     */
    subscribeEvents({ intervalMs = 5000, onEvents, onError } = {}) {
      let lastSeq = null;
      let stopped = false;

      const tick = async () => {
        if (stopped) return;
        try {
          const data = await api("GET", "/api/events");
          const events = data.events || [];
          // The log is ordered by seq; take only what we have not seen.
          const fresh =
            lastSeq == null ? events : events.filter((ev) => ev.seq > lastSeq);
          if (fresh.length) {
            lastSeq = Math.max(...fresh.map((ev) => ev.seq));
            onEvents && onEvents(fresh);
          }
        } catch (e) {
          onError && onError(mapHttpError(e));
        }
      };

      tick();
      pollTimer = setInterval(tick, intervalMs);

      return () => {
        stopped = true;
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
      };
    },

    // ---- Unsupported operations: typed errors, never throws ----
    async validateChanges() {
      return {
        ok: false,
        error: {
          type: "unsupported",
          message: "the workspace draft-ops model has no backend equivalent yet (read-only adapter)",
        },
      };
    },
    async applyChanges() {
      return {
        ok: false,
        error: {
          type: "unsupported",
          message: "backend writes go through missions/jobs/approvals, not workspace draft ops",
        },
      };
    },
    async requestAction() {
      return {
        ok: false,
        error: {
          type: "unsupported",
          message: "dispatch is gated by human approval; not wired from this adapter yet",
        },
      };
    },
    async queryMemory() {
      return {
        ok: false,
        error: {
          type: "unsupported",
          message: "the control-service exposes no shared-memory HTTP endpoint",
        },
      };
    },
  };
}
