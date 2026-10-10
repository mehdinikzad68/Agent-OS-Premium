// Skill 08 — provider-neutral adapter contract acceptance tests.
// Pure modules only (adapter + model), no components (guardrail).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRegistry } from "../src/model/registry.js";
import {
  createMockAdapter,
  DEFAULT_NAV_CAPABILITIES,
} from "../src/adapter/mockAdapter.js";
import { resolveNavItems } from "../src/model/manifest.js";
import { buildSeedState } from "../src/model/seed.js";

const SRC_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src");

function demoRegistry() {
  return createRegistry([
    { id: "hermes", kind: "orchestrator", name: "Hermes" },
    { id: "dsh", kind: "agent", name: "DSH" },
    { id: "docker", kind: "tool", name: "Docker" },
  ]);
}

test("getCapabilities declares navCapabilities gates (default mock list)", () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const caps = adapter.getCapabilities();
  assert.deepEqual(caps.navCapabilities, DEFAULT_NAV_CAPABILITIES);
  assert.ok(caps.navCapabilities.includes("canvas"));
  // The mock deliberately cannot back live telemetry — the UI must
  // show that entry as unavailable with an explanation.
  assert.ok(!caps.navCapabilities.includes("live-telemetry"));
});

test("navCapabilities is a copy: mutating the result cannot poison the adapter", () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  const first = adapter.getCapabilities().navCapabilities;
  first.push("hacked-in");
  const second = adapter.getCapabilities().navCapabilities;
  assert.ok(!second.includes("hacked-in"));
  assert.equal(second.length, DEFAULT_NAV_CAPABILITIES.length);
});

test("acceptance: a second adapter with different capabilities changes nav gating without component changes", () => {
  const registry = demoRegistry();
  const seed = buildSeedState();

  // Two providers, same manifest, same pure resolver — only the
  // capability fact reported by each adapter differs.
  const mock = createMockAdapter({ registry });
  const extended = createMockAdapter({
    registry,
    navCapabilities: [...DEFAULT_NAV_CAPABILITIES, "live-telemetry"],
  });

  const gatedMock = resolveNavItems(seed.manifest, {
    capabilities: mock.getCapabilities().navCapabilities,
  });
  const gatedExtended = resolveNavItems(seed.manifest, {
    capabilities: extended.getCapabilities().navCapabilities,
  });

  const telMock = gatedMock.find((i) => i.id === "telemetry");
  const telExtended = gatedExtended.find((i) => i.id === "telemetry");
  assert.ok(telMock, "seed must contain the telemetry entry");
  assert.equal(telMock.available, false);
  assert.deepEqual(telMock.missingCapabilities, ["live-telemetry"]);
  assert.equal(telExtended.available, true);

  // Entries the extended provider does NOT gate must be unchanged.
  const homeMock = gatedMock.find((i) => i.id === "home");
  const homeExtended = gatedExtended.find((i) => i.id === "home");
  assert.equal(homeMock.available, homeExtended.available);
});

test("declared-unsupported methods return typed errors instead of throwing", async () => {
  const adapter = createMockAdapter({ registry: demoRegistry() });
  for (const method of [
    "getExecutionSnapshot",
    "subscribeEvents",
    "requestAction",
  ]) {
    const res = await adapter[method]("global");
    assert.equal(res.ok, false, `${method} must report ok:false`);
    assert.equal(res.error.type, "unsupported", `${method} error type`);
    assert.equal(typeof res.error.message, "string");
    assert.ok(res.error.message.length > 0);
    // Four-fact model: getCapabilities must agree with behaviour.
    const cap = adapter.getCapabilities().capabilities[method];
    assert.equal(cap.supported, false);
    assert.equal(typeof cap.explanation, "string");
  }
});

// Acceptance: renderer code contains no URL strings. This is a
// repeatable source scan (the "grep check" of skill 08). Widened to
// CSS in phase 9: the Google Fonts CDN @import in src/index.css was
// replaced by the self-hosted ./fonts.css (public/fonts/ files), so
// the whole src/ tree is now free of http(s) URL strings.
test("renderer source contains no URL strings", () => {
  const offenders = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.(js|jsx|css)$/.test(entry.name)) continue;
      const text = readFileSync(full, "utf8");
      if (/https?:\/\//.test(text)) offenders.push(full);
    }
  };
  walk(SRC_ROOT);
  assert.deepEqual(offenders, [], `URL strings found in: ${offenders.join(", ")}`);
});

// ---- Phase 0 regression tests (audit ISS-01 / ISS-02) ----
// These are source scans in the same style as the URL check above. They guard
// against the two React-layer regressions the pure-model suite cannot reach
// (there is no component test harness yet — see the audit's ISS-06).

const readSrc = (rel) => readFileSync(join(SRC_ROOT, rel), "utf8");

test("ISS-01: the app never touches localStorage directly (single persistence path)", () => {
  const app = readSrc("App.jsx");
  // The workspace record (adapter/storage.js) is the ONLY writer. A second
  // writer on the legacy key held the same list twice and duplicated every
  // custom tool on reload.
  assert.equal(
    /localStorage/.test(app),
    false,
    "App.jsx must not use localStorage directly; use the storage adapter"
  );
});

test("ISS-01: the legacy scratch key lives only in the storage adapter", () => {
  const offenders = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.(js|jsx)$/.test(entry.name)) continue;
      // storage.js is allowed to reference the key (it owns the migration);
      // no other module may.
      if (full.replace(/\\/g, "/").endsWith("adapter/storage.js")) continue;
      if (/agentos-neural-tools-v1/.test(readFileSync(full, "utf8"))) {
        offenders.push(full);
      }
    }
  };
  walk(SRC_ROOT);
  assert.deepEqual(offenders, [], `legacy key referenced outside storage.js: ${offenders.join(", ")}`);
});

test("ISS-02: the app hands the shared-memory provider to the adapter", () => {
  const app = readSrc("App.jsx");
  // Without `memory`, queryMemory is declared unsupported and every retrieval
  // in the UI fails, even though the policy and provider exist.
  assert.ok(
    /createMockAdapter\(\s*\{\s*registry:\s*seed\.registry,\s*memory:\s*seed\.memory\s*\}/.test(app),
    "createMockAdapter must receive { registry, memory: seed.memory }"
  );
});

test("ISS-02: the status card explains an unsupported memory provider", () => {
  const card = readSrc("components/StatusCard.jsx");
  // skill 08: unsupported is shown WITH an explanation, never as a working
  // Retrieve button that only errors.
  assert.ok(/memory\.supported === false/.test(card), "StatusCard must gate on memory.supported");
  assert.ok(/memoryUnsupported/.test(card), "StatusCard must render the explanation string");
});
