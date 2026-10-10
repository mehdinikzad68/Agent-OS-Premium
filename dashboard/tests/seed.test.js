import { test } from "node:test";
import assert from "node:assert/strict";
import { AGENTS, LINKS } from "../src/data.js";
import {
  buildSeedState,
  toAgents,
  toLinks,
  buildRegistry,
  buildConnections,
} from "../src/model/seed.js";
import { getCoordinator, entitiesOfKind } from "../src/model/registry.js";
import { missionCounts, runsForAgent, telemetryLevel } from "../src/model/runtime.js";
import {
  buildClusters,
  subagentFreshness,
} from "../src/model/runtime.js";
import {
  resolveNavItems,
  validateManifest,
  validatePages,
  RENDERER_ALLOWLIST,
} from "../src/model/manifest.js";

test("seed state is fully valid (no validation errors)", () => {
  const seed = buildSeedState();
  assert.deepEqual(seed.errors, []);
});

test("toAgents reproduces the baseline agents plus the shared-memory node (skill 05)", () => {
  const registry = buildRegistry();
  assert.deepStrictEqual(toAgents(registry), [
    ...AGENTS,
    {
      id: "shared-mem",
      name: "Shared Memory",
      sub: { en: "Shared vault (mock)", fa: "خزانه‌ی مشترک (mock)" },
      status: "running",
      tok: "0",
      load: 0,
      seen: "17:46:02",
    },
  ]);
});

test("toLinks reproduces the baseline links plus the memory-read fibers (skill 05)", () => {
  const registry = buildRegistry();
  const connections = buildConnections(registry);
  assert.deepStrictEqual(toLinks(connections), [
    ...LINKS,
    { from: "dsh", to: "shared-mem" },
    { from: "seo", to: "shared-mem" },
  ]);
});

test("the registry has exactly one orchestrator (coordinator by role)", () => {
  const seed = buildSeedState();
  assert.equal(entitiesOfKind(seed.registry, "orchestrator").length, 1);
  assert.equal(getCoordinator(seed.registry).id, "hermes");
});

test("baseline connections satisfy the port compatibility rules", () => {
  const seed = buildSeedState();
  assert.deepEqual(seed.connections.errors, []);
  assert.equal(seed.connections.list.length, LINKS.length + 2);
  assert.deepEqual(
    seed.connections.list.map((c) => c.type),
    [
      "control",
      "tool-access",
      "tool-access",
      "control",
      "tool-access",
      "tool-access",
      "memory-read",
      "memory-read",
    ]
  );
});

test("the shared-memory seed has a provider, policy and MOCK notes (skill 05)", () => {
  const seed = buildSeedState();
  assert.equal(seed.memory.providerName, "obsidian");
  assert.equal(seed.memory.provider.readOnly, true);
  assert.equal(seed.memory.provider.simulated, true);
  assert.deepEqual(seed.memory.policy.grants, [
    { agentId: "dsh", scope: "obsidian/notes", access: "read" },
  ]);
  assert.deepEqual(seed.memory.scopes, ["obsidian/notes", "obsidian/ops"]);
  assert.ok(seed.memory.notes.every((n) => n.source.includes("MOCK")));
});

test("the runtime seed replays the flight log as runs", () => {
  const seed = buildSeedState();
  const counts = missionCounts(seed.runtime, "mission-mock-001");
  assert.equal(counts.total, 7);
  assert.equal(counts.succeeded, 5);
  assert.equal(counts.waiting, 1);
  assert.equal(counts.failed, 1);
  assert.equal(counts.finished, 6);
  assert.equal(runsForAgent(seed.runtime, "dsh").length, 4);
});

// ---- Skill 06: mission mock-002 scenario ----

test("mission mock-002 spawns three parallel children (skill 06)", () => {
  const seed = buildSeedState();
  const counts = missionCounts(seed.runtime, "mission-mock-002");
  assert.equal(counts.total, 5);
  assert.equal(counts.succeeded, 3); // parent + seo + nested
  assert.equal(counts.waiting, 1); // dsh child on approval
  assert.equal(counts.failed, 1); // hermes child
  assert.equal(counts.finished, 4);
  // Only the waiting child is still active.
  const activeChildren = Object.values(seed.runtime.runs).filter(
    (r) => r.parentRunId === "run-m2-dsh" && !["succeeded", "failed", "cancelled"].includes(r.state)
  );
  assert.equal(activeChildren.length, 1);

  const parent = seed.runtime.runs["run-m2-dsh"];
  assert.equal(parent.agentId, "dsh");
  assert.equal(parent.parentRunId, null);
  assert.equal(parent.assignedTask, "Refactor dashboard module");

  const children = Object.values(seed.runtime.runs).filter(
    (r) => r.parentRunId === "run-m2-dsh"
  );
  assert.equal(children.length, 3);

  const seo = seed.runtime.runs["run-m2-seo"];
  assert.equal(seo.state, "succeeded");
  assert.equal(
    seed.runtime.runs["run-m2-seo-n"].parentRunId,
    "run-m2-seo"
  ); // nested child

  const waiting = seed.runtime.runs["run-m2-dsh-c"];
  assert.equal(waiting.state, "waiting");
  assert.equal(waiting.waitingReason, "approval");

  const failed = seed.runtime.runs["run-m2-hermes"];
  assert.equal(failed.state, "failed");
  assert.equal(failed.error, "Bundle validation failed");
});

test("mission mock-002 records the memory retrieval (scenario 7)", () => {
  const seed = buildSeedState();
  assert.equal(seed.runtime.retrievals.length, 1);
  const retrieval = seed.runtime.retrievals[0];
  assert.equal(retrieval.runId, "run-m2-seo");
  assert.equal(retrieval.scope, "obsidian/notes");
  assert.equal(retrieval.state, "succeeded");
});

test("mission mock-002 assigns subagent telemetry freshness", () => {
  const seed = buildSeedState();
  assert.equal(subagentFreshness(seed.runtime, "dsh"), "fresh");
  assert.equal(subagentFreshness(seed.runtime, "antigravity"), "stale");
  // hermes's provider reports NO subagent telemetry —
  // the UI must say so, never an established zero.
  assert.equal(subagentFreshness(seed.runtime, "hermes"), "unavailable");
  // dsh owns a cluster of 3 children (1 active);
  // seo owns a second cluster: its nested child.
  const clusters = buildClusters(seed.runtime);
  assert.equal(clusters.length, 2);
  const dshCluster = clusters.find((c) => c.agentId === "dsh");
  assert.ok(dshCluster);
  assert.equal(dshCluster.counts.total, 3);
  assert.equal(dshCluster.counts.active, 1);
  assert.equal(dshCluster.counts.waiting, 1);
  assert.equal(dshCluster.counts.failed, 1);
  const seoCluster = clusters.find((c) => c.agentId === "seo");
  assert.ok(seoCluster);
  assert.equal(seoCluster.counts.total, 1);
  assert.equal(seoCluster.counts.succeeded, 1);
});

test("the seed store is labeled demo and reports telemetry honestly", () => {
  const seed = buildSeedState();
  assert.equal(seed.runtime.source, "demo");
  assert.equal(telemetryLevel(seed.runtime, "dsh"), "full");
  assert.equal(telemetryLevel(seed.runtime, "unknown-agent"), "unavailable");
});

test("the manifest seed resolves to 10 visible entries in order; capability gating explains the unavailable one", () => {
  const seed = buildSeedState();
  const resolved = resolveNavItems(seed.manifest, {
    capabilities: ["canvas", "timeline", "resource-tables", "schema-forms"],
    permissions: ["workspace.read"],
  });
  assert.equal(resolved.length, 10);
  // Hidden ≠ unavailable: every seed entry is visible.
  assert.ok(resolved.every((i) => i.visible));
  assert.deepEqual(
    resolved.map((i) => i.id),
    [
      "home",
      "missions",
      "hubs",
      "agents",
      "models",
      "tools",
      "history",
      "pages",
      "settings",
      "telemetry",
    ]
  );
  // 9 entries are supported; the telemetry entry requires
  // "live-telemetry" — unavailable WITH an explanation.
  const available = resolved.filter((i) => i.available);
  assert.equal(available.length, 9);
  const telemetry = resolved.find((i) => i.id === "telemetry");
  assert.equal(telemetry.available, false);
  assert.deepEqual(telemetry.missingCapabilities, ["live-telemetry"]);
  assert.ok(telemetry.unavailableReason.includes("live-telemetry"));
});

test("the seed pages cover every nav route with known renderers (skill 07)", () => {
  const seed = buildSeedState();
  assert.equal(validateManifest(seed.manifest).ok, true);
  assert.equal(validatePages(seed.pages).ok, true);
  assert.equal(seed.pages.length, seed.manifest.items.length);
  const navRoutes = new Set(seed.manifest.items.map((i) => i.route));
  for (const page of seed.pages) {
    assert.ok(navRoutes.has(page.route), `nav route exists for ${page.route}`);
    assert.ok(RENDERER_ALLOWLIST.includes(page.renderer), `known renderer: ${page.renderer}`);
    assert.ok(page.title && page.title.en && page.title.fa, `localized title: ${page.id}`);
  }
  assert.equal(seed.models.length, 3);
  assert.equal(seed.errors.length, 0);
});
