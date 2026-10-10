// Persistence tests: storage interface, validation on
// load, export/import safety (skill 04 acceptance).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRegistry } from "../src/model/registry.js";
import {
  WORKSPACE_KEY,
  WORKSPACE_SCHEMA_VERSION,
  LEGACY_TOOLS_KEY,
  createLocalStorageAdapter,
  createMemoryStorage,
  exportWorkspace,
  loadWorkspace,
  parseImport,
  saveWorkspace,
} from "../src/adapter/storage.js";

function demoRegistry() {
  return createRegistry([
    { id: "hermes", kind: "orchestrator", name: "Hermes" },
    { id: "dsh", kind: "agent", name: "DSH" },
    { id: "docker", kind: "tool", name: "Docker" },
    { id: "wp", kind: "tool", name: "WordPress" },
    { id: "mem", kind: "memory", name: "Shared Memory", provider: "obsidian" },
  ]);
}

const workspace = {
  customTools: [{ id: "mytool", name: "My Tool", custom: true, parent: "docker" }],
  connections: [
    { id: "conn-hermes-control-dsh", from: "hermes", to: "dsh", type: "control", state: "enabled" },
  ],
  view: {
    schemaVersion: 1,
    positions: { dsh: { x: 100, y: 200 } },
    fiberGeometry: {},
    groups: {},
    hidden: [],
    savedViews: [],
    viewport: { zoom: 1, panX: 0, panY: 0 },
  },
};

// Custom tools are NORMALIZED on load (audit ISS-03/ISS-16): display fields
// the renderer reads unconditionally (sub[lang], status) get safe defaults so
// a partial import can never crash the UI or produce NaN status counters.
const normalizeTool = (t) => ({
  ...t,
  sub: { en: t.name, fa: t.name },
  status: "offline",
  tok: "0",
  load: 0,
  seen: "00:00",
  custom: true,
});

test("save + load round-trips non-secret workspace data", async () => {
  const storage = createLocalStorageAdapter(createMemoryStorage());
  await saveWorkspace(storage, workspace);
  const loaded = await loadWorkspace(storage, { registry: demoRegistry() });
  assert.deepEqual(loaded.customTools, [normalizeTool(workspace.customTools[0])]);
  assert.deepEqual(loaded.connections, workspace.connections);
  assert.equal(loaded.view.positions.dsh.x, 100);
  assert.equal(loaded.view.positions.dsh.y, 200);
  assert.deepEqual(loaded.errors, []);
});

test("malformed JSON keeps defaults and reports a readable error", async () => {
  const raw = createMemoryStorage();
  raw.setItem(WORKSPACE_KEY, "{not json");
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  assert.deepEqual(loaded.customTools, []);
  assert.equal(loaded.connections, null);
  assert.ok(loaded.errors.some((e) => e.includes("malformed JSON")));
});

test("a wrong schemaVersion is rejected with a readable error", async () => {
  const raw = createMemoryStorage();
  raw.setItem(WORKSPACE_KEY, JSON.stringify({ schemaVersion: 99, sections: {} }));
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  assert.deepEqual(loaded.customTools, []);
  assert.ok(loaded.errors.some((e) => e.includes("schemaVersion")));
});

test("a malformed section keeps its default, other sections still load", async () => {
  const record = {
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    sections: {
      customTools: [{ id: "ok", name: "OK" }, { name: "no-id" }],
      connections: "not-an-array",
      view: { schemaVersion: 1, positions: { dsh: { x: 1, y: 2 } }, bad: 0 },
    },
  };
  const raw = createMemoryStorage();
  raw.setItem(WORKSPACE_KEY, JSON.stringify(record));
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  assert.deepEqual(loaded.customTools, [normalizeTool({ id: "ok", name: "OK" })]);
  assert.equal(loaded.connections, null); // malformed section -> keep defaults
  assert.deepEqual(loaded.view.positions, { dsh: { x: 1, y: 2, locked: false } });
  assert.ok(loaded.errors.some((e) => e.includes("customTools[1]")));
  assert.ok(loaded.errors.some((e) => e.includes("connections")));
});

test("invalid connections are dropped with the model's reason", async () => {
  const record = {
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    sections: {
      customTools: [],
      connections: [
        { id: "c1", from: "hermes", to: "dsh", type: "control", state: "enabled" },
        { id: "c2", from: "dsh", to: "hermes", type: "control", state: "enabled" },
        { id: "c3", from: "hermes", to: "ghost", type: "control", state: "enabled" },
      ],
    },
  };
  const raw = createMemoryStorage();
  raw.setItem(WORKSPACE_KEY, JSON.stringify(record));
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  assert.deepEqual(loaded.connections.map((c) => c.id), ["c1"]);
  assert.ok(loaded.errors.some((e) => e.includes("c2")));
  assert.ok(loaded.errors.some((e) => e.includes("c3")));
});

// ---- Phase 0 regression tests (audit ISS-03 / ISS-16) ----

test("ISS-03: a custom tool missing `sub` is normalized so the renderer cannot crash", async () => {
  // A tool without `sub` is valid JSON and passes the id/name check, but the
  // renderer reads a.sub[lang] unconditionally (StatusCard, App labelFor).
  const record = {
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    sections: {
      customTools: [{ id: "bare", name: "Bare Tool" }],
      connections: null,
      view: null,
    },
  };
  const raw = createMemoryStorage();
  raw.setItem(WORKSPACE_KEY, JSON.stringify(record));
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  const t = loaded.customTools[0];
  assert.ok(t, "the tool survives validation");
  assert.equal(typeof t.sub, "object");
  assert.equal(t.sub.en, "Bare Tool");
  assert.equal(t.sub.fa, "Bare Tool");
  // repair is silent: it is a display default, not a configuration error
  assert.deepEqual(loaded.errors, []);
});

test("ISS-03/16: an unknown status and non-numeric load are coerced to safe defaults", async () => {
  const record = {
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    sections: {
      customTools: [{ id: "weird", name: "Weird", status: "banana", load: "high" }],
      connections: null,
      view: null,
    },
  };
  const raw = createMemoryStorage();
  raw.setItem(WORKSPACE_KEY, JSON.stringify(record));
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  const t = loaded.customTools[0];
  // STATUS_COLOR[status] and counts[status]++ both index these keys; an
  // unknown status would render as undefined and count as NaN.
  assert.equal(t.status, "offline");
  assert.equal(t.load, 0);
  assert.deepEqual(loaded.errors, []);
});

test("ISS-03: a valid bilingual sub and a known status are preserved verbatim", async () => {
  const record = {
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    sections: {
      customTools: [
        {
          id: "good",
          name: "Good",
          sub: { en: "Good tool", fa: "ابزار خوب" },
          status: "running",
          load: 42,
          tok: "1.2k",
          seen: "12:00:00",
        },
      ],
      connections: null,
      view: null,
    },
  };
  const raw = createMemoryStorage();
  raw.setItem(WORKSPACE_KEY, JSON.stringify(record));
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  const t = loaded.customTools[0];
  assert.deepEqual(t.sub, { en: "Good tool", fa: "ابزار خوب" });
  assert.equal(t.status, "running");
  assert.equal(t.load, 42);
  assert.equal(t.tok, "1.2k");
  assert.equal(t.seen, "12:00:00");
});

test("ISS-01: loadWorkspace is idempotent — reloading does not duplicate custom tools", async () => {
  const storage = createLocalStorageAdapter(createMemoryStorage());
  await saveWorkspace(storage, {
    ...workspace,
    customTools: [{ id: "one", name: "One" }],
  });
  const first = await loadWorkspace(storage, { registry: demoRegistry() });
  const second = await loadWorkspace(storage, { registry: demoRegistry() });
  assert.equal(first.customTools.length, 1);
  // A second load must return the SAME single tool, not two copies.
  assert.equal(second.customTools.length, 1);
  assert.equal(second.customTools[0].id, "one");
});

test("exported JSON contains no token-like strings", () => {
  const json = exportWorkspace(workspace);
  // long base64/base64url-ish blobs (>= 32 chars) are the token pattern
  assert.equal(/\b[A-Za-z0-9+/=_-]{32,}\b/.test(json), false);
  assert.equal(json.includes("secret"), false);
  assert.equal(json.includes("password"), false);
  assert.equal(json.includes("token"), false);
});

test("parseImport accepts a valid export and reports section errors for preview", () => {
  const parsed = parseImport(exportWorkspace(workspace), { registry: demoRegistry() });
  assert.equal(parsed.ok, true);
  assert.deepEqual(parsed.workspace.customTools, [normalizeTool(workspace.customTools[0])]);
  assert.deepEqual(parsed.errors, []);

  const dirty = JSON.stringify({
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    sections: {
      customTools: [],
      connections: [{ id: "x", from: "hermes", to: "nope", type: "control" }],
      view: null,
    },
  });
  const dirtyParsed = parseImport(dirty, { registry: demoRegistry() });
  assert.equal(dirtyParsed.ok, true); // preview still available
  assert.ok(dirtyParsed.errors.some((e) => e.includes("connection[0]")));
  assert.equal(dirtyParsed.workspace.connections.length, 0);
});

test("parseImport rejects malformed input with readable errors and never throws", () => {
  const fatal = parseImport("{broken", { registry: demoRegistry() });
  assert.equal(fatal.ok, false);
  assert.ok(fatal.errors[0].includes("malformed JSON"));

  const wrongVersion = parseImport(
    JSON.stringify({ schemaVersion: 2, sections: {} }),
    { registry: demoRegistry() }
  );
  assert.equal(wrongVersion.ok, false);
  assert.ok(wrongVersion.errors[0].includes("schemaVersion"));

  const notObject = parseImport("[1,2,3]", { registry: demoRegistry() });
  assert.equal(notObject.ok, false);
});

test("the legacy phase-2 key migrates once and is removed", async () => {
  const raw = createMemoryStorage();
  raw.setItem(LEGACY_TOOLS_KEY, JSON.stringify([{ id: "old", name: "Old Tool" }]));
  const storage = createLocalStorageAdapter(raw);

  const loaded = await loadWorkspace(storage, { registry: demoRegistry() });
  assert.deepEqual(loaded.customTools, [normalizeTool({ id: "old", name: "Old Tool" })]);
  assert.equal(raw.getItem(LEGACY_TOOLS_KEY), null);

  // the migrated record now round-trips through the new key
  const again = await loadWorkspace(storage, { registry: demoRegistry() });
  assert.deepEqual(again.customTools, [normalizeTool({ id: "old", name: "Old Tool" })]);
  assert.deepEqual(again.errors, []);
});

test("storage failures are best-effort, never thrown", async () => {
  const broken = {
    getItem: () => {
      throw new Error("quota exceeded");
    },
    setItem: () => {
      throw new Error("private mode");
    },
    removeItem: () => {
      throw new Error("locked");
    },
  };
  const storage = createLocalStorageAdapter(broken);
  assert.equal(await storage.read(WORKSPACE_KEY), null);
  assert.equal(await storage.write(WORKSPACE_KEY, "{}"), false);
  const loaded = await loadWorkspace(storage, { registry: demoRegistry() });
  assert.deepEqual(loaded.customTools, []);
  assert.deepEqual(loaded.errors, []);
});

// ---- Skill 07: navigation manifest + pages sections ----

const NAV_MANIFEST = {
  schemaVersion: 1,
  items: [
    {
      id: "home",
      label: { en: "Home", fa: "خانه" },
      icon: "home",
      order: 10,
      route: "/home",
      renderer: "command-canvas",
      visible: true,
      capabilities: [],
      permissions: [],
    },
  ],
};

const NAV_PAGES = [
  {
    id: "page-home",
    route: "/home",
    renderer: "command-canvas",
    title: { en: "Home", fa: "خانه" },
    props: {},
  },
];

test("manifest and pages round-trip through storage", async () => {
  const storage = createLocalStorageAdapter(createMemoryStorage());
  await saveWorkspace(storage, {
    ...workspace,
    manifest: NAV_MANIFEST,
    pages: NAV_PAGES,
  });
  const loaded = await loadWorkspace(storage, { registry: demoRegistry() });
  assert.deepEqual(loaded.manifest, NAV_MANIFEST);
  assert.deepEqual(loaded.pages, NAV_PAGES);
  assert.deepEqual(loaded.errors, []);
});

test("absent navigation sections keep the built-in defaults", async () => {
  const storage = createLocalStorageAdapter(createMemoryStorage());
  await saveWorkspace(storage, workspace); // no manifest / pages keys
  const loaded = await loadWorkspace(storage, { registry: demoRegistry() });
  assert.equal(loaded.manifest, null);
  assert.equal(loaded.pages, null);
});

test("a malformed manifest section keeps defaults and reports a readable error", async () => {
  const raw = createMemoryStorage();
  raw.setItem(
    WORKSPACE_KEY,
    JSON.stringify({
      schemaVersion: WORKSPACE_SCHEMA_VERSION,
      savedAt: null,
      sections: {
        // invalid: missing label/route/renderer + unknown icon
        manifest: { schemaVersion: 1, items: [{ id: "x", icon: "unicorn" }] },
      },
    })
  );
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  assert.equal(loaded.manifest, null);
  assert.ok(loaded.errors.some((e) => e.includes("manifest")));
  assert.ok(loaded.errors.some((e) => e.includes("unicorn")));
});

test("a malformed pages section keeps defaults and reports a readable error", async () => {
  const raw = createMemoryStorage();
  raw.setItem(
    WORKSPACE_KEY,
    JSON.stringify({
      schemaVersion: WORKSPACE_SCHEMA_VERSION,
      savedAt: null,
      sections: {
        pages: [
          { id: "p1", route: "no-leading-slash", renderer: "nope", title: { en: "P", fa: "پ" } },
        ],
      },
    })
  );
  const loaded = await loadWorkspace(createLocalStorageAdapter(raw), {
    registry: demoRegistry(),
  });
  assert.equal(loaded.pages, null);
  assert.ok(loaded.errors.some((e) => e.includes("pages")));
  assert.ok(loaded.errors.some((e) => e.includes("nope")));
});

test("export carries the navigation sections and import validates them", () => {
  const json = exportWorkspace({
    ...workspace,
    manifest: NAV_MANIFEST,
    pages: NAV_PAGES,
  });
  const parsed = parseImport(json, { registry: demoRegistry() });
  assert.equal(parsed.ok, true);
  assert.deepEqual(parsed.workspace.manifest, NAV_MANIFEST);
  assert.deepEqual(parsed.workspace.pages, NAV_PAGES);
  assert.deepEqual(parsed.errors, []);

  // An import with a broken manifest is NOT fatal — section-level
  // errors are listed for the preview and the default is kept.
  const bad = JSON.parse(json);
  bad.sections.manifest.items[0].icon = "unicorn";
  const parsedBad = parseImport(JSON.stringify(bad), { registry: demoRegistry() });
  assert.equal(parsedBad.ok, true);
  assert.equal(parsedBad.workspace.manifest, null);
  assert.ok(parsedBad.errors.some((e) => e.includes("manifest")));
});
