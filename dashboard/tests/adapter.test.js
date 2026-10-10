// Contract tests for the MOCK adapter (skill 08).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRegistry } from "../src/model/registry.js";
import { createMockAdapter } from "../src/adapter/mockAdapter.js";
import { buildSeedState } from "../src/model/seed.js";
import {
  validateManifest,
  validatePages,
  resolveNavItems,
  visibleNavItems,
} from "../src/model/manifest.js";

function demoRegistry() {
  return createRegistry([
    { id: "hermes", kind: "orchestrator", name: "Hermes" },
    { id: "dsh", kind: "agent", name: "DSH" },
    { id: "docker", kind: "tool", name: "Docker" },
    { id: "mem", kind: "memory", name: "Shared Memory", provider: "obsidian" },
  ]);
}

const base = {
  agents: [
    { id: "hermes", name: "Hermes", status: "running" },
    { id: "dsh", name: "DSH", status: "running" },
  ],
  connections: [
    {
      id: "conn-hermes-control-dsh",
      from: "hermes",
      to: "dsh",
      type: "control",
      state: "enabled",
    },
  ],
};

test("getCapabilities reports the four-fact capability model", () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const caps = adapter.getCapabilities();
  assert.equal(caps.label, "mock");
  assert.equal(caps.simulated, true);
  for (const [name, cap] of Object.entries(caps.capabilities)) {
    for (const fact of ["supported", "authorized", "available", "configured"]) {
      assert.equal(typeof cap[fact], "boolean", `${name}.${fact}`);
    }
    if (!cap.supported) {
      assert.ok(cap.explanation, `${name} unsupported needs an explanation`);
    }
  }
  assert.equal(caps.capabilities.applyChanges.supported, true);
  assert.equal(caps.capabilities.validateChanges.supported, true);
  assert.equal(caps.capabilities.queryMemory.supported, false);
});

test("applyChanges accepts valid operations and returns new state", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base,
    changes: [
      {
        opId: "op-1",
        status: "pending",
        op: "addConnection",
        connection: {
          id: "conn-hermes-memory-read-dsh",
          from: "hermes",
          to: "dsh",
          type: "memory-read",
        },
      },
      {
        opId: "op-2",
        status: "pending",
        op: "setConnectionState",
        connectionId: "conn-hermes-control-dsh",
        state: "disabled",
      },
    ],
  });
  assert.equal(res.ok, true);
  assert.equal(res.label, "mock");
  assert.equal(res.simulated, true);
  assert.equal(res.status, "ok");
  assert.equal(res.results.length, 2);
  assert.ok(res.results.every((r) => r.status === "accepted"));
  assert.equal(res.connections.length, 2);
  assert.equal(
    res.connections.find((c) => c.id === "conn-hermes-control-dsh").state,
    "disabled"
  );
  // base state is never mutated (pure)
  assert.equal(base.connections.length, 1);
  assert.equal(base.connections[0].state, "enabled");
});

test("one rejected operation yields a partial result, never full success", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const baseWithTool = {
    agents: [...base.agents, { id: "docker", name: "Docker", status: "offline" }],
    connections: [...base.connections],
  };
  const res = await adapter.applyChanges({
    base: baseWithTool,
    changes: [
      {
        opId: "op-ok",
        status: "pending",
        op: "addConnection",
        connection: {
          id: "conn-hermes-tool-access-docker",
          from: "hermes",
          to: "docker",
          type: "tool-access",
        },
      },
      {
        opId: "op-bad",
        status: "pending",
        op: "addConnection",
        connection: {
          id: "conn-dsh-control-hermes",
          from: "dsh",
          to: "hermes",
          type: "control",
        },
      },
    ],
  });
  assert.equal(res.status, "partial");
  const bad = res.results.find((r) => r.opId === "op-bad");
  assert.equal(bad.status, "rejected");
  assert.ok(bad.reason);
  // only the accepted op is in the resulting state
  assert.equal(res.connections.length, 2);
  assert.ok(res.connections.some((c) => c.id === "conn-hermes-tool-access-docker"));
  assert.ok(!res.connections.some((c) => c.id === "conn-dsh-control-hermes"));
});

test("scripted failurePlan forces a deterministic rejection", async () => {
  const adapter = createMockAdapter({
    registry: demoRegistry(),
    failurePlan: { "op-x": "scripted rejection for testing" },
  });
  const res = await adapter.applyChanges({
    base,
    changes: [
      {
        opId: "op-x",
        status: "pending",
        op: "removeConnection",
        connectionId: "conn-hermes-control-dsh",
      },
    ],
  });
  assert.equal(res.status, "failed");
  assert.equal(res.results[0].status, "rejected");
  assert.equal(res.results[0].reason, "scripted rejection for testing");
  assert.equal(res.connections.length, 1); // untouched
});

test("removeEntity cascades to attached connections and refuses the coordinator", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const withTool = {
    agents: [...base.agents, { id: "docker", name: "Docker", status: "offline" }],
    connections: [
      ...base.connections,
      {
        id: "conn-hermes-tool-access-docker",
        from: "hermes",
        to: "docker",
        type: "tool-access",
        state: "enabled",
      },
    ],
  };
  const res = await adapter.applyChanges({
    base: withTool,
    changes: [{ opId: "op-rm", status: "pending", op: "removeEntity", entityId: "docker" }],
  });
  assert.equal(res.status, "ok");
  assert.ok(res.agents.every((a) => a.id !== "docker"));
  assert.ok(res.connections.every((c) => c.id !== "conn-hermes-tool-access-docker"));

  const blocked = await adapter.applyChanges({
    base,
    changes: [{ opId: "op-co", status: "pending", op: "removeEntity", entityId: "hermes" }],
  });
  assert.equal(blocked.results[0].status, "rejected");
  assert.ok(blocked.results[0].reason.includes("coordinator"));
});

test("addEntity validates shape and duplicates", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base,
    changes: [
      { opId: "op-1", status: "pending", op: "addEntity", entity: { id: "newtool", name: "New Tool" } },
      { opId: "op-2", status: "pending", op: "addEntity", entity: { id: "dsh", name: "Duplicate" } },
      { opId: "op-3", status: "pending", op: "addEntity", entity: { id: "", name: "No id" } },
    ],
  });
  assert.equal(res.status, "partial");
  assert.equal(res.results[0].status, "accepted");
  assert.equal(res.results[1].status, "rejected");
  assert.equal(res.results[2].status, "rejected");
  assert.equal(res.agents.length, 3);
});

test("changePermission records per-agent scope policy", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base,
    changes: [
      {
        opId: "op-p",
        status: "pending",
        op: "changePermission",
        agentId: "dsh",
        scope: "memory:obsidian/notes",
        allowed: true,
      },
    ],
  });
  assert.equal(res.status, "ok");
  assert.deepEqual(res.agents.find((a) => a.id === "dsh").permissions, {
    "memory:obsidian/notes": true,
  });

  const denied = await adapter.applyChanges({
    base,
    changes: [
      {
        opId: "op-p2",
        status: "pending",
        op: "changePermission",
        agentId: "ghost",
        scope: "x",
        allowed: true,
      },
    ],
  });
  assert.equal(denied.results[0].status, "rejected");
});

test("unsupported operations return typed errors instead of throwing", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base,
    changes: [{ opId: "op-u", status: "pending", op: "teleportEntity", entityId: "dsh" }],
  });
  assert.equal(res.results[0].status, "rejected");
  assert.ok(res.results[0].reason.includes("unsupported"));

  const snap = await adapter.getExecutionSnapshot("all");
  assert.equal(snap.ok, false);
  assert.equal(snap.error.type, "unsupported");

  const mem = await adapter.queryMemory({ text: "notes" });
  assert.equal(mem.ok, false);
  assert.equal(mem.error.type, "unsupported");

  const list = await adapter.listResources("unknown-kind");
  assert.equal(list.ok, false);
  assert.equal(list.error.type, "unsupported_kind");
});

test("an invalid changeSet returns a typed error, never throws", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({});
  assert.equal(res.ok, false);
  assert.equal(res.error.type, "invalid_change_set");
});

test("listResources/getResource read the synced workspace", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  adapter.syncWorkspace(base);
  const list = await adapter.listResources("connection", { text: "control" });
  assert.equal(list.ok, true);
  assert.equal(list.total, 1);
  const got = await adapter.getResource("agent", "dsh");
  assert.equal(got.ok, true);
  assert.equal(got.item.id, "dsh");
  const missing = await adapter.getResource("agent", "nope");
  assert.equal(missing.ok, false);
  assert.equal(missing.error.type, "not_found");
});

test("validateChanges is a dry run: results without state", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.validateChanges({
    base,
    changes: [
      {
        opId: "op-1",
        status: "pending",
        op: "removeConnection",
        connectionId: "conn-hermes-control-dsh",
      },
    ],
  });
  assert.equal(res.ok, true);
  assert.equal(res.status, "ok");
  assert.equal(res.results[0].status, "accepted");
  assert.equal(res.connections, undefined); // no state returned by validation
  assert.equal(base.connections.length, 1);
});

// ---- Shared-memory retrieval (skill 05) ----

function memoryAdapter() {
  const seed = buildSeedState();
  const adapter = createMockAdapter({
    registry: seed.registry,
    memory: seed.memory,
  });
  adapter.syncWorkspace({ agents: [], connections: seed.connections.list });
  return adapter;
}

test("queryMemory allows an agent with connection and grant", async () => {
  const adapter = memoryAdapter();
  const res = await adapter.queryMemory({
    agentId: "dsh",
    scope: "obsidian/notes",
  });
  assert.equal(res.ok, true);
  assert.equal(res.label, "mock");
  assert.equal(res.simulated, true);
  assert.equal(res.readOnly, true);
  assert.ok(Array.isArray(res.items));
  assert.ok(res.items.length > 0);
  assert.ok(res.items.every((i) => i.source.includes("MOCK")));
});

test("queryMemory filters mock items by text", async () => {
  const adapter = memoryAdapter();
  const res = await adapter.queryMemory({
    agentId: "dsh",
    scope: "obsidian/notes",
    text: "fiber",
  });
  assert.equal(res.ok, true);
  assert.equal(res.items.length, 1);
  assert.equal(res.items[0].id, "note-002");
});

test("queryMemory denies an agent with a connection but no grant", async () => {
  const adapter = memoryAdapter();
  // seo has a configured memory-read connection in the
  // seed but NO policy grant — three separate facts.
  const res = await adapter.queryMemory({
    agentId: "seo",
    scope: "obsidian/notes",
  });
  assert.equal(res.ok, false);
  assert.equal(res.error.type, "access_denied");
  assert.ok(res.error.message.includes("seo"));
  assert.ok(res.error.message.includes("obsidian/notes"));
});

test("queryMemory is per-scope: granted scope works, another is denied", async () => {
  const adapter = memoryAdapter();
  const ok = await adapter.queryMemory({
    agentId: "dsh",
    scope: "obsidian/notes",
  });
  assert.equal(ok.ok, true);
  const denied = await adapter.queryMemory({
    agentId: "dsh",
    scope: "obsidian/ops",
  });
  assert.equal(denied.ok, false);
  assert.equal(denied.error.type, "access_denied");
});

test("queryMemory reports not_configured without an enabled connection", async () => {
  const adapter = memoryAdapter();
  const res = await adapter.queryMemory({
    agentId: "docker",
    scope: "obsidian/notes",
  });
  assert.equal(res.ok, false);
  assert.equal(res.error.type, "not_configured");
});

test("queryMemory treats a disabled connection as not configured", async () => {
  const seed = buildSeedState();
  const adapter = createMockAdapter({
    registry: seed.registry,
    memory: seed.memory,
  });
  adapter.syncWorkspace({
    agents: [],
    connections: seed.connections.list.map((c) =>
      c.type === "memory-read" ? { ...c, state: "disabled" } : c
    ),
  });
  const res = await adapter.queryMemory({
    agentId: "dsh",
    scope: "obsidian/notes",
  });
  assert.equal(res.ok, false);
  assert.equal(res.error.type, "not_configured");
});

test("queryMemory validates the request shape", async () => {
  const adapter = memoryAdapter();
  const noAgent = await adapter.queryMemory({ scope: "x" });
  assert.equal(noAgent.ok, false);
  assert.equal(noAgent.error.type, "invalid_request");
  const noScope = await adapter.queryMemory({ agentId: "dsh" });
  assert.equal(noScope.ok, false);
  assert.equal(noScope.error.type, "invalid_request");
});

test("queryMemory is unsupported without a memory provider", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  assert.equal(adapter.getCapabilities().capabilities.queryMemory.supported, false);
  const res = await adapter.queryMemory({ agentId: "dsh", scope: "x" });
  assert.equal(res.ok, false);
  assert.equal(res.error.type, "unsupported");
});

// ---- Skill 07: navigation / page manifest ops through the adapter ----

let navSeq = 0;
const navOp = (op, payload) => {
  navSeq += 1;
  return { opId: `nav-op-${navSeq}`, status: "pending", op, ...payload };
};

function navBase() {
  const seed = buildSeedState();
  return { seed, base: { ...base, manifest: seed.manifest, pages: seed.pages } };
}

const AUDIT_ITEM = {
  id: "audit",
  icon: "shield",
  route: "/audit",
  renderer: "resource-table",
  order: 999,
  label: { en: "Audit log", fa: "گزارش ممیزی" },
  visible: true,
  capabilities: [],
  permissions: [],
};

test("addNavItem applies through the adapter and keeps the manifest valid", async () => {
  const { base: b } = navBase();
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base: b,
    changes: [navOp("addNavItem", { item: AUDIT_ITEM })],
  });
  assert.equal(res.status, "ok");
  assert.equal(res.results[0].status, "accepted");
  assert.equal(res.manifest.items.length, b.manifest.items.length + 1);
  assert.ok(res.manifest.items.some((i) => i.id === "audit"));
  assert.equal(validateManifest(res.manifest).ok, true);
  // The base state is never mutated (pure adapter).
  assert.equal(b.manifest.items.length, 10);
});

test("malformed nav entries are rejected with readable reasons", async () => {
  const { base: b } = navBase();
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base: b,
    changes: [
      navOp("addNavItem", { item: { ...AUDIT_ITEM, id: "home", route: "/home" } }),
      navOp("addNavItem", { item: { ...AUDIT_ITEM, id: "bad-renderer", renderer: "magic-panel" } }),
      navOp("addNavItem", { item: { ...AUDIT_ITEM, id: "bad-icon", icon: "unicorn" } }),
    ],
  });
  assert.equal(res.status, "failed"); // every operation rejected
  assert.equal(res.results.length, 3);
  assert.ok(res.results.every((r) => r.status === "rejected" && r.reason));
  assert.ok(res.results[0].reason.includes("duplicate"));
  assert.ok(res.results[1].reason.includes("magic-panel"));
  assert.ok(res.results[2].reason.includes("unicorn"));
  // Nothing was applied.
  assert.equal(res.manifest.items.length, b.manifest.items.length);
  assert.equal(validateManifest(res.manifest).ok, true);
});

test("moveNav swaps order values and respects list boundaries", async () => {
  const { base: b } = navBase();
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base: b,
    changes: [navOp("moveNav", { navId: "home", delta: 1 })],
  });
  assert.equal(res.status, "ok");
  const home = res.manifest.items.find((i) => i.id === "home");
  const missions = res.manifest.items.find((i) => i.id === "missions");
  assert.equal(home.order, 20); // swapped with missions
  assert.equal(missions.order, 10);
  assert.equal(validateManifest(res.manifest).ok, true);

  const edge = await adapter.applyChanges({
    base: b,
    changes: [navOp("moveNav", { navId: "telemetry", delta: 1 })],
  });
  assert.equal(edge.results[0].status, "rejected");
  assert.ok(edge.results[0].reason.includes("already at the"));

  const unknown = await adapter.applyChanges({
    base: b,
    changes: [navOp("moveNav", { navId: "nope", delta: -1 })],
  });
  assert.ok(unknown.results[0].reason.includes("unknown nav item"));
});

test("setNavVisibility hides an entry without deleting its data", async () => {
  const { base: b } = navBase();
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base: b,
    changes: [navOp("setNavVisibility", { navId: "tools", visible: false })],
  });
  assert.equal(res.status, "ok");
  // Data intact — only the flag changed.
  assert.equal(res.manifest.items.length, b.manifest.items.length);
  const tools = res.manifest.items.find((i) => i.id === "tools");
  assert.ok(tools);
  assert.equal(tools.visible, false);
  assert.equal(tools.route, "/tools");
  // The entry is NOT in the visible navigation anymore.
  const visible = visibleNavItems(resolveNavItems(res.manifest));
  assert.equal(visible.length, 9);
  assert.equal(visible.some((i) => i.id === "tools"), false);

  const unknown = await adapter.applyChanges({
    base: b,
    changes: [navOp("setNavVisibility", { navId: "nope", visible: false })],
  });
  assert.equal(unknown.results[0].status, "rejected");
});

test("addPage validates the renderer and route uniqueness", async () => {
  const { base: b } = navBase();
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const good = {
    id: "p-audit",
    route: "/audit",
    renderer: "resource-table",
    title: { en: "Audit", fa: "ممیزی" },
    props: { source: "connections" },
  };
  const res = await adapter.applyChanges({
    base: b,
    changes: [navOp("addPage", { page: good })],
  });
  assert.equal(res.status, "ok");
  assert.equal(res.pages.length, b.pages.length + 1);
  assert.equal(validatePages(res.pages).ok, true);

  const bad = await adapter.applyChanges({
    base: b,
    changes: [
      navOp("addPage", { page: { ...good, id: "p1", renderer: "magic-panel" } }),
      navOp("addPage", { page: { ...good, id: "p2", route: "/agents" } }),
    ],
  });
  assert.equal(bad.status, "failed");
  assert.ok(bad.results[0].reason.includes("magic-panel"));
  assert.ok(bad.results[1].reason.includes("duplicate route"));
  assert.equal(bad.pages.length, b.pages.length);
});

test("nav ops without base manifest/pages are rejected, never invented", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base: { agents: base.agents, connections: base.connections },
    changes: [
      navOp("addNavItem", { item: AUDIT_ITEM }),
      navOp("moveNav", { navId: "home", delta: 1 }),
      navOp("setNavVisibility", { navId: "home", visible: false }),
      navOp("addPage", { page: { id: "p-audit", route: "/audit", renderer: "timeline", title: { en: "A", fa: "آ" } } }),
    ],
  });
  assert.equal(res.status, "failed");
  assert.equal(res.results.length, 4);
  assert.ok(res.results.every((r) => r.status === "rejected"));
  assert.ok(res.results[0].reason.includes("base.manifest was not provided"));
  assert.ok(res.results[3].reason.includes("base.pages was not provided"));
  assert.equal(res.manifest, null);
  assert.equal(res.pages, null);
});

test("a mixed batch reports partial — never full — success", async () => {
  const { base: b } = navBase();
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const res = await adapter.applyChanges({
    base: b,
    changes: [
      navOp("addNavItem", { item: AUDIT_ITEM }), // accepted
      navOp("addNavItem", { item: { ...AUDIT_ITEM, id: "home", route: "/home" } }), // rejected
      navOp("setNavVisibility", { navId: "models", visible: false }), // accepted
    ],
  });
  assert.equal(res.status, "partial"); // NOT "ok" — one op was rejected
  assert.equal(res.results[0].status, "accepted");
  assert.equal(res.results[1].status, "rejected");
  assert.equal(res.results[2].status, "accepted");
  // Accepted operations landed; rejected ones did not.
  assert.ok(res.manifest.items.some((i) => i.id === "audit"));
  assert.equal(res.manifest.items.find((i) => i.id === "models").visible, false);
  assert.equal(res.manifest.items.length, b.manifest.items.length + 1);
});
