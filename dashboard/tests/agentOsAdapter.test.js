// Contract tests for the real, READ-ONLY Agent OS adapter (skill 08).
// No network: global.fetch is stubbed so these run anywhere.
import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  createAgentOsAdapter,
  AGENT_OS_RESOURCE_KINDS,
} from "../src/adapter/agentOsAdapter.js";

// Simple fetch stub. `routes` maps "METHOD /path" -> { status, body }.
let routes = {};
let fetchCalls = [];

function installFetch() {
  globalThis.fetch = async (url, opts = {}) => {
    const key = `${(opts.method || "GET").toUpperCase()} ${url}`;
    fetchCalls.push(key);
    const r = routes[key];
    if (!r) {
      return { ok: false, status: 404, json: async () => ({ error: { code: "not_found", message: "no route" } }) };
    }
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  };
}

beforeEach(() => {
  routes = {};
  fetchCalls = [];
  installFetch();
});

afterEach(() => {
  delete globalThis.fetch;
});

test("getCapabilities: real adapter is not simulated and declares reads", () => {
  const a = createAgentOsAdapter();
  const caps = a.getCapabilities();
  assert.equal(caps.label, "agent-os");
  assert.equal(caps.simulated, false);
  assert.equal(caps.capabilities.listResources.supported, true);
  assert.equal(caps.capabilities.getExecutionSnapshot.supported, true);
  // Writes are honestly unsupported.
  assert.equal(caps.capabilities.applyChanges.supported, false);
  assert.ok(caps.capabilities.applyChanges.explanation);
  assert.equal(caps.capabilities.queryMemory.supported, false);
});

test("listResources unwraps the backend collection and normalizes executors", async () => {
  routes["GET /api/missions"] = {
    status: 200,
    body: { missions: [{ id: "m_1", title: "Refactor auth", state: "active" }] },
  };
  routes["GET /api/executors"] = { status: 200, body: { executors: ["fake-executor"] } };

  const a = createAgentOsAdapter();
  const m = await a.listResources("mission");
  assert.equal(m.ok, true);
  assert.equal(m.simulated, false);
  assert.equal(m.items.length, 1);
  assert.equal(m.items[0].id, "m_1");

  const ex = await a.listResources("executor");
  assert.equal(ex.ok, true);
  assert.deepEqual(ex.items[0], { id: "fake-executor", name: "fake-executor" });
});

test("listResources rejects unknown kinds and filters by text", async () => {
  routes["GET /api/jobs"] = {
    status: 200,
    body: { jobs: [{ id: "j_1", title: "Run tests" }, { id: "j_2", title: "Lint" }] },
  };
  const a = createAgentOsAdapter();
  const bad = await a.listResources("agent");
  assert.equal(bad.ok, false);
  assert.equal(bad.error.type, "unsupported_kind");

  const filtered = await a.listResources("job", { text: "lint" });
  assert.equal(filtered.ok, true);
  assert.equal(filtered.items.length, 1);
  assert.equal(filtered.items[0].id, "j_2");
});

test("HTTP failures map to typed errors, never throw", async () => {
  routes["GET /api/missions"] = { status: 401, body: { error: { code: "unauthorized" } } };
  const a = createAgentOsAdapter();
  const res = await a.listResources("mission");
  assert.equal(res.ok, false);
  assert.equal(res.error.type, "unauthorized");
  assert.equal(res.error.status, 401);
});

test("getExecutionSnapshot combines jobs + events", async () => {
  routes["GET /api/jobs"] = { status: 200, body: { jobs: [{ id: "j_1" }] } };
  routes["GET /api/events"] = { status: 200, body: { events: [{ seq: 1, kind: "job_created" }] } };
  const a = createAgentOsAdapter();
  const snap = await a.getExecutionSnapshot();
  assert.equal(snap.ok, true);
  assert.equal(snap.simulated, false);
  assert.equal(snap.jobs.length, 1);
  assert.equal(snap.events.length, 1);
});

test("getResource: unsupported single-fetch kinds return typed error", async () => {
  const a = createAgentOsAdapter();
  const res = await a.getResource("approval", "a_1");
  assert.equal(res.ok, false);
  assert.equal(res.error.type, "unsupported");
});

test("write methods return typed unsupported errors", async () => {
  const a = createAgentOsAdapter();
  for (const method of ["applyChanges", "validateChanges", "requestAction", "queryMemory"]) {
    const res = await a[method]({});
    assert.equal(res.ok, false, method);
    assert.equal(res.error.type, "unsupported", method);
  }
});

test("Agent OS resource kinds cover the backend's read surface", () => {
  for (const k of ["mission", "job", "approval", "executor", "project", "event"]) {
    assert.ok(AGENT_OS_RESOURCE_KINDS.includes(k), k);
  }
});
