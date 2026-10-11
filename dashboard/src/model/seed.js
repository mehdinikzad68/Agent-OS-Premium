// Seed: adapts the baseline demo data (data.js) into the new
// models. This is the bridge between the legacy static demo and
// the model-driven architecture.
//
// Everything produced here is DEMO data — it must be labeled as
// such wherever it is displayed (data truthfulness).
//
// Kind mapping (documented judgment call, derived from each
// entity's demo role):
//   hermes       -> orchestrator (coordinator, by ROLE not by id)
//   dsh          -> agent        (code agent)
//   seo          -> agent        (content optimizer agent)
//   docker       -> tool         (workspace runtime)
//   wordpress    -> tool         (site deployer)
//   antigravity  -> tool         (IDE bridge)

import { AGENTS, LINKS, T } from "../data.js";
import { createRegistry } from "./registry.js";
import { createConnections } from "./connections.js";
import { createDefaultView } from "./view.js";
import { createDraft } from "./draft.js";
import { createPolicy } from "./memory.js";
import { createMockMemoryProvider } from "../adapter/memoryProvider.js";
import {
  createExecutionStore,
  applyEvents,
  setTelemetryLevel,
  setSubagentFreshness,
} from "./runtime.js";
import { MANIFEST_SCHEMA_VERSION, validateManifest, validatePages } from "./manifest.js";

const KIND_BY_ID = {
  hermes: "orchestrator",
  dsh: "agent",
  seo: "agent",
  docker: "tool",
  wordpress: "tool",
  antigravity: "tool",
};

const ROLE_BY_ID = {
  hermes: "orchestrator",
  dsh: "code-agent",
  seo: "content-optimizer",
  docker: "workspace-runtime",
  wordpress: "site-deployer",
  antigravity: "ide-bridge",
};

const CAPABILITIES_BY_ID = {
  hermes: ["orchestrate", "memory.read", "memory.write"], // memory.write is RESERVED
  dsh: ["code.edit", "code.review"],
  seo: ["content.publish"],
  docker: ["container.build", "workspace.run"],
  wordpress: ["site.deploy", "db.credential.rotate"],
  antigravity: ["ide.bridge"],
};

// Connection type for each baseline link. Defaults to
// "tool-access" for links not listed explicitly.
const TYPE_BY_LINK = {
  "hermes>dsh": "control",
  "hermes>seo": "control",
  "hermes>docker": "tool-access",
  "hermes>wordpress": "tool-access",
  "hermes>antigravity": "tool-access",
  "docker>wordpress": "tool-access",
};

function entityFromAgent(a) {
  const entity = {
    id: a.id,
    kind: KIND_BY_ID[a.id] || "tool",
    name: a.name,
    description: a.sub,
    role: ROLE_BY_ID[a.id],
    capabilities: CAPABILITIES_BY_ID[a.id] || [],
    status: a.status,
    tok: a.tok,
    load: a.load,
    seen: a.seen,
  };
  if (a.cmd) entity.cmd = a.cmd;
  if (a.icon) entity.icon = a.icon;
  return entity;
}

// Shared-memory node (skill 05). The provider is a
// VALUE ("obsidian"), not a dependency — the mock
// provider is swappable and nothing reads a vault.
// memory.write stays RESERVED (model-only, unsupported).
const MEMORY_ENTITY = {
  id: "shared-mem",
  kind: "memory",
  name: "Shared Memory",
  description: {
    en: "Shared vault (mock)",
    fa: "خزانه‌ی مشترک (mock)",
  },
  role: "shared-memory",
  capabilities: ["memory.read"],
  provider: "obsidian",
  status: "running",
  tok: "0",
  load: 0,
  seen: "17:46:02",
};

/** Build the registry from the baseline agents
 *  plus the shared-memory node. */
export function buildRegistry() {
  return createRegistry([...AGENTS.map(entityFromAgent), MEMORY_ENTITY]);
}

function linkType(from, to) {
  return TYPE_BY_LINK[`${from}>${to}`] || "tool-access";
}

// Memory-read connections (skill 05). dsh has a policy
// grant for obsidian/notes; seo has a configured
// connection but NO grant — its retrievals are denied.
// Access policy and connection state are separate facts.
const MEMORY_CONNECTIONS = [
  { from: "dsh", to: "shared-mem", type: "memory-read" },
  { from: "seo", to: "shared-mem", type: "memory-read" },
];

/** Build the configured connections from the baseline
 *  links plus the shared-memory read fibers. */
export function buildConnections(registry) {
  return createConnections(
    registry,
    [
      ...LINKS.map((l) => ({ from: l.from, to: l.to, type: linkType(l.from, l.to) })),
      ...MEMORY_CONNECTIONS,
    ]
  );
}

// ---- Runtime seed: one deterministic mock mission ----
// Fixed reference date so the demo is reproducible.
const DEMO_EPOCH = Date.UTC(2026, 0, 1, 17, 0, 0);
const DEMO_MISSION = "mission-mock-001";
const DEMO_MISSION_2 = "mission-mock-002";

const RUN_SPECS = [
  { runId: "run-dsh-1731", agentId: "dsh", minute: 31, activity: "Code change", terminal: "completed" },
  { runId: "run-docker-1734", agentId: "docker", minute: 34, activity: "Container build", terminal: "completed" },
  { runId: "run-wp-1737", agentId: "wordpress", minute: 37, activity: "Plugin install", terminal: "completed" },
  { runId: "run-seo-1739", agentId: "seo", minute: 39, activity: "Approval request", terminal: "waiting", waitingReason: "approval" },
  { runId: "run-dsh-1741", agentId: "dsh", minute: 41, activity: "Code change", terminal: "completed" },
  { runId: "run-antigravity-1743", agentId: "antigravity", minute: 43, activity: "Session dropped", terminal: "failed", error: "Session dropped" },
  { runId: "run-hermes-1746", agentId: "hermes", minute: 46, activity: "Heartbeat", terminal: "completed" },
];

/** Build the execution store from the baseline flight-log data
 *  plus the skill-06 mock mission. */
export function buildRuntime() {
  let store = createExecutionStore("demo");
  let sequence = 0;
  const events = [];
  for (const spec of RUN_SPECS) {
    const base = DEMO_EPOCH + spec.minute * 60_000;
    const mk = (type, offsetMs, extra = {}) => ({
      eventId: `${spec.runId}-${type}`,
      sequence: sequence++,
      occurredAt: base + offsetMs,
      receivedAt: base + offsetMs,
      missionId: DEMO_MISSION,
      runId: spec.runId,
      agentId: spec.agentId,
      type,
      ...extra,
    });
    events.push(mk("run.created", 0));
    events.push(mk("run.started", 1));
    events.push(mk("run.activity", 2, { reportedActivity: spec.activity }));
    if (spec.terminal === "waiting") {
      events.push(mk("run.waiting", 3, { waitingReason: spec.waitingReason }));
    } else if (spec.terminal === "failed") {
      events.push(mk("run.failed", 3, { error: spec.error }));
    } else {
      events.push(mk("run.completed", 3));
    }
  }

  // ---- Mission mock-002 (skill 06) ----
  // Required mock scenarios in one mission:
  //   1. a parent spawns three children in parallel
  //   2. one child succeeds (seo)
  //   3. one child waits on approval (dsh)
  //   4. one child fails (hermes)
  //   5. the parent aggregates the results
  //   6. a nested child under the succeeded child
  //   7. a memory retrieval and return on that child
  const M2_T0 = DEMO_EPOCH + 50 * 60_000;
  const M2_RUNS = [
    {
      runId: "run-m2-dsh",
      agentId: "dsh",
      parentRunId: null,
      assignedTask: "Refactor dashboard module",
      activity: "Aggregating subagent results",
      activityAt: 48,
      endAt: 55,
    },
    {
      runId: "run-m2-seo",
      agentId: "seo",
      parentRunId: "run-m2-dsh",
      assignedTask: "Optimize page metadata",
      activity: "Optimize metadata",
      activityAt: 6,
      endAt: 40,
    },
    {
      runId: "run-m2-dsh-c",
      agentId: "dsh",
      parentRunId: "run-m2-dsh",
      assignedTask: "Rewrite import graph",
      activity: "Rewrite imports",
      activityAt: 5,
      waitingAt: 12,
    },
    {
      runId: "run-m2-hermes",
      agentId: "hermes",
      parentRunId: "run-m2-dsh",
      assignedTask: "Validate production bundle",
      activity: "Validate bundle",
      activityAt: 7,
      failAt: 20,
      error: "Bundle validation failed",
    },
    {
      runId: "run-m2-seo-n",
      agentId: "seo",
      parentRunId: "run-m2-seo",
      assignedTask: "Fetch changelog entries",
      activity: "Fetch changelog",
      activityAt: 10,
      endAt: 30,
    },
  ];
  const M2_START = {
    "run-m2-dsh": 0,
    "run-m2-seo": 2,
    "run-m2-dsh-c": 3,
    "run-m2-hermes": 4,
    "run-m2-seo-n": 8,
  };
  for (const spec of M2_RUNS) {
    const base = M2_T0 + (M2_START[spec.runId] || 0) * 1000;
    const mk2 = (type, offsetSec, extra = {}) => ({
      eventId: `${spec.runId}-${type}`,
      sequence: sequence++,
      occurredAt: base + offsetSec * 1000,
      receivedAt: base + offsetSec * 1000,
      missionId: DEMO_MISSION_2,
      runId: spec.runId,
      agentId: spec.agentId,
      parentRunId: spec.parentRunId || undefined,
      assignedTask: spec.assignedTask,
      type,
      ...extra,
    });
    events.push(mk2("run.created", 0));
    events.push(mk2("run.started", 1));
    events.push(
      mk2("run.activity", spec.activityAt, { reportedActivity: spec.activity })
    );
    if (spec.runId === "run-m2-seo") {
      // memory retrieval and return (scenario 7)
      events.push(mk2("memory.query.started", 12, { scope: "obsidian/notes" }));
      events.push(mk2("memory.query.completed", 14, { scope: "obsidian/notes" }));
    }
    if (spec.waitingAt != null) {
      events.push(mk2("run.waiting", spec.waitingAt, { waitingReason: "approval" }));
    } else if (spec.failAt != null) {
      events.push(mk2("run.failed", spec.failAt, { error: spec.error }));
    } else {
      events.push(mk2("run.completed", spec.endAt));
    }
  }

  const { store: withEvents } = applyEvents(store, events);
  store = withEvents;
  // The demo "provider" reports full telemetry for its known agents.
  for (const id of Object.keys(KIND_BY_ID)) {
    store = setTelemetryLevel(store, id, "full").store;
  }
  // Subagent telemetry freshness (skill 06): dsh reports a
  // fresh cluster; antigravity is stale; hermes's provider
  // reports NO subagent telemetry — the UI must say so and
  // never show an established zero.
  for (const [id, level] of [
    ["dsh", "fresh"],
    ["seo", "fresh"],
    ["docker", "fresh"],
    ["wordpress", "fresh"],
    ["antigravity", "stale"],
    ["hermes", "unavailable"],
  ]) {
    store = setSubagentFreshness(store, id, level).store;
  }
  return store;
}

// ---- Manifest seed: the baseline navigation ----
// Optional 5th element: required capabilities. The telemetry
// entry declares "live-telemetry" which the mock does NOT
// support — the UI must show it as unavailable WITH an
// explanation (capability gating, skill 07).

const NAV_SEED = [
  ["home", "home", "/home", "command-canvas"],
  ["missions", "rocket", "/missions", "timeline"],
  ["hubs", "network", "/hubs", "resource-table"],
  ["agents", "bot", "/agents", "resource-table"],
  ["models", "cpu", "/models", "resource-table"],
  ["tools", "wrench", "/tools", "resource-table"],
  ["history", "history", "/history", "timeline"],
  ["pages", "file-text", "/pages", "resource-table"],
  ["settings", "settings", "/settings", "schema-form"],
  ["telemetry", "activity", "/telemetry", "resource-table", ["live-telemetry"]],
  // Backend live view (Phase 2): real Agent OS missions/jobs/approvals/events.
  // Gated on the "backend-live" capability, which the app reports only when
  // the header connection badge is healthy — so this entry is unavailable
  // (with an explanation) until a real backend is connected.
  ["backend", "globe", "/backend", "backend-live", ["backend-live"]],
];

/** Build the default navigation manifest from the i18n catalog. */
export function buildManifest() {
  return {
    schemaVersion: MANIFEST_SCHEMA_VERSION,
    items: NAV_SEED.map(([id, icon, route, renderer, capabilities], i) => ({
      id,
      icon,
      route,
      renderer,
      order: (i + 1) * 10,
      label: { en: T.en.nav[i], fa: T.fa.nav[i] },
      visible: true,
      capabilities: capabilities || [],
      permissions: [],
    })),
  };
}

// ---- Standard pages seed (skill 07) ----
// One declarative page per baseline route. Props are DATA only.

const PAGE_FIELDS_SETTINGS = [
  { id: "storageKey", label: { en: "Storage key", fa: "کلید ذخیره‌سازی" }, type: "text", value: "agentos-workspace-v1" },
  { id: "schemaVersion", label: { en: "Workspace schema version", fa: "نسخه اسکیمای فضای کاری" }, type: "text", value: "1" },
  { id: "dataLabel", label: { en: "Data label", fa: "برچسب داده" }, type: "text", value: "MOCK / demo" },
  { id: "simulated", label: { en: "Simulated adapter (MOCK)", fa: "آداپتر شبیه‌سازی‌شده (MOCK)" }, type: "toggle", value: true },
  { id: "backendUrl", label: { en: "Backend URL", fa: "آدرس بک‌اند" }, type: "text", value: "" },
];

const PAGE_SOURCES = {
  home: null, // command-canvas is hosted by the app shell
  missions: "runs",
  hubs: "connections",
  agents: "agents",
  models: "models",
  tools: "tools",
  history: "runs",
  pages: "pages",
  settings: "workspace",
  telemetry: "freshness",
};

/** Build the default standard pages, aligned with the nav routes. */
export function buildPages() {
  const pages = NAV_SEED.map(([id, , route, renderer], i) => {
    const source = PAGE_SOURCES[id];
    const props = {};
    if (source) props.source = source;
    if (id === "settings") props.fields = PAGE_FIELDS_SETTINGS;
    return {
      id: `page-${id}`,
      route,
      renderer,
      title: { en: T.en.nav[i], fa: T.fa.nav[i] },
      props,
    };
  });
  return pages;
}

// ---- Models seed (skill 07 resource-table source) ----
// MOCK demo data — labeled at display time.

const MODELS_SEED = [
  { id: "mdl-primary", name: "Primary reasoning model", provider: "mock-provider-a", state: "active" },
  { id: "mdl-fast", name: "Fast draft model", provider: "mock-provider-b", state: "active" },
  { id: "mdl-local", name: "Local offline model", provider: "mock-local", state: "standby" },
];

// ---- Shared-memory seed (skill 05) ----
// MOCK notes: deterministic, labeled MOCK at display
// time. Source references are data, never instructions.
const MEMORY_NOTES = [
  {
    id: "note-001",
    title: "Release checklist",
    scope: "obsidian/notes",
    source: "vault://release-checklist · MOCK",
    tags: ["release", "process"],
    body: "Ship the dashboard only after the tests pass.",
  },
  {
    id: "note-002",
    title: "Fiber layout notes",
    scope: "obsidian/notes",
    source: "vault://fiber-layout · MOCK",
    tags: ["design", "canvas"],
    body: "Keep the coordinator fixed at the visual center.",
  },
  {
    id: "note-003",
    title: "Credential rotation log",
    scope: "obsidian/ops",
    source: "vault://cred-rotation · MOCK",
    tags: ["ops", "security"],
    body: "Rotate tier-3 credentials through the approval gate.",
  },
];

const MEMORY_GRANTS = [
  // dsh: configured connection AND a per-scope grant.
  { agentId: "dsh", scope: "obsidian/notes", access: "read" },
  // seo has a connection but no grant: denied.
];

/** Build the shared-memory configuration: policy,
 *  mock provider, notes and available scopes. */
export function buildMemory() {
  const policy = createPolicy(MEMORY_GRANTS);
  const provider = createMockMemoryProvider({
    provider: "obsidian",
    notes: MEMORY_NOTES,
  });
  return {
    providerName: "obsidian",
    policy,
    provider,
    notes: MEMORY_NOTES,
    scopes: [...new Set(MEMORY_NOTES.map((n) => n.scope))],
  };
}

/**
 * Build the complete seed state. Any validation problem is
 * collected in `errors` — an empty array means the baseline is
 * fully valid.
 */
export function buildSeedState() {
  const errors = [];

  const registry = buildRegistry();
  errors.push(...registry.errors);

  const connections = buildConnections(registry);
  errors.push(...connections.errors);

  const view = createDefaultView();
  const draft = createDraft();
  const runtime = buildRuntime();
  const manifest = buildManifest();
  const pages = buildPages();

  const manifestCheck = validateManifest(manifest);
  errors.push(...manifestCheck.errors.map((e) => `manifest: ${e}`));

  const pagesCheck = validatePages(pages);
  errors.push(...pagesCheck.errors.map((e) => `pages: ${e}`));

  return {
    registry,
    connections,
    view,
    draft,
    runtime,
    manifest,
    pages,
    models: MODELS_SEED.map((m) => ({ ...m })),
    memory: buildMemory(),
    errors,
  };
}

// ---- Adapters back to the shapes the current UI consumes ----
// These exist so the existing components keep working unchanged
// while the models are introduced. They are removed as the
// components migrate to the models directly.

/** Registry -> the agent-shaped objects the current UI renders. */
export function toAgents(registry) {
  return Object.values(registry.byId).map((e) => {
    const a = {
      id: e.id,
      name: e.name,
      sub: e.description,
      status: e.status,
      tok: e.tok,
      load: e.load,
      seen: e.seen,
    };
    if (e.cmd) a.cmd = e.cmd;
    if (e.icon) a.icon = e.icon;
    return a;
  });
}

/** Connection list -> the {from, to} link objects the UI renders. */
export function toLinks(connections) {
  const list = Array.isArray(connections) ? connections : connections.list;
  return list.map((c) => ({ from: c.from, to: c.to }));
}
