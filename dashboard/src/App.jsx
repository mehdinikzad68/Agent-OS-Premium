// Minified name in bundle: Fs.
import { useEffect, useMemo, useState } from "react";
import { Brain, Cable, Check, Crosshair, LayoutGrid, Search, SlidersHorizontal, X } from "lucide-react";
import { APPROVALS, T } from "./data.js";
import { buildSeedState, toAgents } from "./model/seed.js";
import { getCoordinator } from "./model/registry.js";
import { connectionId, canConnect } from "./model/connections.js";
import { setPosition, setFiberMidpoint, resetLayout } from "./model/view.js";
import {
  addChange,
  applyResultsToDraft,
  createDraft,
  discardDraft as clearDraft,
  summarizeDraft,
  createHistory,
  commit,
  undo,
  redo,
} from "./model/draft.js";
import DraftBar from "./components/DraftBar.jsx";
import WorkspaceTools from "./components/WorkspaceTools.jsx";
import MemoryInspector from "./components/MemoryInspector.jsx";
import Timeline from "./components/Timeline.jsx";
import NavCustomizer from "./components/NavCustomizer.jsx";
import PageRouter from "./pages/PageRouter.jsx";
import { createMockAdapter } from "./adapter/mockAdapter.js";
import { createAgentOsAdapter } from "./adapter/agentOsAdapter.js";
import { useConnection } from "./connection/ConnectionProvider.jsx";
import { scopesForAgent } from "./model/memory.js";
import {
  createLocalStorageAdapter,
  exportWorkspace,
  loadWorkspace,
  saveWorkspace,
} from "./adapter/storage.js";
import { STATUS_COLOR, SUN } from "./scene/colors.js";
import NeuralScene from "./scene/NeuralScene.jsx";
import Header from "./components/Header.jsx";
import Sidebar from "./components/Sidebar.jsx";
import StatusCard from "./components/StatusCard.jsx";
import Gate from "./components/Gate.jsx";
import AddTool from "./components/AddTool.jsx";
import Btn from "./components/Btn.jsx";
import {
  buildClusters,
  runSubtree,
  getRun,
  subagentFreshness,
} from "./model/runtime.js";

// ---- Phase 7: routing + capability gating (skill 07) ----
const HOME_ROUTE = "/home";
// Capability gating comes FROM the adapter's getCapabilities()
// (skill 08): a manifest entry that requires anything the provider
// does not declare renders as unavailable WITH an explanation —
// never silently, never as an established zero. Swapping the
// adapter changes the gating without touching components.
// Permissions the demo workspace holds. Hiding a UI action is
// NOT authorization — a real backend must enforce permissions.
const GRANTED_PERMISSIONS = ["workspace.read", "workspace.write", "runtime.read"];

// NOTE: custom tools are persisted in exactly ONE place — the validated
// workspace record written by the debounced save effect and read by
// loadWorkspace. An earlier version also read/wrote the pre-workspace
// scratch key here, which held the same list twice and duplicated every
// custom tool on reload. That key is migrated once, inside
// adapter/storage.js, and is never touched from the UI (enforced by
// tests/contract.test.js).

export default function App() {
  const [lang, setLang] = useState("fa");
  const t = T[lang];
  const rtl = lang === "fa";

  const seed = useMemo(() => buildSeedState(), []);
  const [agents, setAgents] = useState(() => [...toAgents(seed.registry)]);
  const [adding, setAdding] = useState(false);

  // ---- Phase 3: interaction mode, view state, draft ----
  const [mode, setModeState] = useState("observe");
  const [view, setView] = useState(() => seed.view);
  const [baseConnections, setBaseConnections] = useState(() => seed.connections.list);
  const [draft, setDraft] = useState(() => createDraft());
  const [changeHistory, setChangeHistory] = useState(() => createHistory());
  const [selectedConnection, setSelectedConnection] = useState(null);
  const [connectFrom, setConnectFrom] = useState(null);

  const setMode = (m) => {
    setModeState(m);
    if (m === "observe") {
      setConnectFrom(null);
      setSelectedConnection(null);
    }
  };

  // Operational connections = configured base + custom-tool fibers.
  const connections = useMemo(() => {
    const custom = agents
      .filter((a) => a.custom)
      .map((a) => ({
        id: connectionId(a.parent || "hermes", "tool-access", a.id),
        from: a.parent || "hermes",
        to: a.id,
        type: "tool-access",
        state: "enabled",
        scope: [],
      }));
    return [...baseConnections, ...custom];
  }, [baseConnections, agents]);

  const kinds = useMemo(() => {
    const map = Object.fromEntries(Object.values(seed.registry.byId).map((e) => [e.id, e.kind]));
    agents.forEach((a) => {
      if (!map[a.id]) map[a.id] = "tool";
    });
    return map;
  }, [seed, agents]);

  const coordinatorId = useMemo(() => getCoordinator(seed.registry)?.id || "hermes", [seed]);

  // ---- Phase 4: mock adapter + storage behind an interface ----
  // Phase 0 fix (audit ISS-02): the shared-memory provider MUST be handed to
  // the adapter. Without it `queryMemory` reports "unsupported" and every
  // retrieval in the UI fails, even though the policy and the provider exist.
  const adapter = useMemo(
    () => createMockAdapter({ registry: seed.registry, memory: seed.memory }),
    [seed]
  );
  // UI feature gates are read from the adapter (skill 08), not
  // hardcoded here — providers differ in what they can back.
  // Computed below, once the live-backend connection state is known.
  const storage = useMemo(() => createLocalStorageAdapter(), []);

  // ---- Phase 2: real Agent OS backend (READ-ONLY adapter) ----
  // This is a SEPARATE data source from the mock adapter above. The command
  // canvas keeps using the mock (its agents/connections have no backend
  // equivalent); the backend-live page reads real missions/jobs/approvals/
  // events through this adapter. It is only "live" when the header connection
  // badge reports a healthy backend.
  const { state: connectionState } = useConnection();
  const agentOs = useMemo(() => createAgentOsAdapter(), []);
  const backendLive = connectionState === "connected" || connectionState === "stale";
  // The "backend-live" nav entry is offered only while a real backend
  // is reachable (skill 07/08 capability gating — never claim a live
  // data source that is not actually connected).
  const capabilities = useMemo(() => {
    const base = adapter.getCapabilities().navCapabilities ?? [];
    return backendLive && !base.includes("backend-live")
      ? [...base, "backend-live"]
      : base;
  }, [adapter, backendLive]);
  const [applying, setApplying] = useState(false);
  const [boot, setBoot] = useState("loading");
  const [bootErrors, setBootErrors] = useState([]);

  // ---- Phase 5: shared-memory node (mock provider) ----
  const memoryId = useMemo(
    () =>
      Object.values(seed.registry.byId).find((e) => e.kind === "memory")?.id,
    [seed]
  );
  const memoryConnections = useMemo(
    () =>
      connections.filter(
        (c) => memoryId && c.to === memoryId && c.type === "memory-read"
      ),
    [connections, memoryId]
  );
  const [memoryEvent, setMemoryEvent] = useState(null);
  const [memoryLog, setMemoryLog] = useState([]);
  const [memoryResult, setMemoryResult] = useState(null);
  const [retrieving, setRetrieving] = useState(false);

  // Layout-only changes are part of the draft summary
  // (they apply locally — no adapter involved).
  const layoutOnly = useMemo(() => {
    const items = [];
    const posCount = Object.keys(view.positions).length;
    const geoCount = Object.keys(view.fiberGeometry).length;
    if (posCount > 0) items.push(`${posCount} position`);
    if (geoCount > 0) items.push(`${geoCount} curvature`);
    return items;
  }, [view]);

  const summary = useMemo(() => summarizeDraft(draft, layoutOnly), [draft, layoutOnly]);
  const hasPending = summary.total > 0;

  // (the legacy-key writer that used to live here was removed — see the
  // note at the top of this file; the debounced save effect below is the
  // single persistence path.)

  const [approvals, setApprovals] = useState(APPROVALS);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [toast, setToast] = useState(null);
  const [burst, setBurst] = useState(null);

  // ---- Phase 6: runtime executions, clusters, timeline ----
  const [selectedRun, setSelectedRun] = useState(null);
  const [expandedClusters, setExpandedClusters] = useState(() => new Set());
  const [missionFilter, setMissionFilter] = useState("all");
  const [activeOnly, setActiveOnly] = useState(false);

  // ---- Phase 7: declarative navigation + standard pages ----
  const [manifest, setManifest] = useState(() => seed.manifest);
  const [pages, setPages] = useState(() => seed.pages);
  const [activeRoute, setActiveRoute] = useState(HOME_ROUTE);
  const [customizingNav, setCustomizingNav] = useState(false);

  const fire = (id) => setBurst({ id, n: Math.random() });
  const flash = (ok, id, msg) => {
    setToast({ ok, id, msg });
    setTimeout(() => setToast(null), 2600);
  };

  // ---- Phase 3 handlers: gestures, draft, simulated apply ----
  const snapshotHistory = () => setChangeHistory((h) => commit(h, { draft, view }));

  const proposeConnection = ({ from, to, type }) => {
    const check = canConnect(seed.registry, connections, { from, to, type });
    if (!check.ok) {
      flash(false, `${from} → ${to}`, check.reason);
      return;
    }
    const connection = { id: connectionId(from, type, to), from, to, type, state: "enabled", scope: [] };
    snapshotHistory();
    setDraft((d) => addChange(d, { op: "addConnection", connection }).draft);
    setSelectedConnection(connection.id);
    flash(true, connection.id, t.draftAdded);
  };

  const disconnectConnection = (id) => {
    snapshotHistory();
    setDraft((d) => addChange(d, { op: "removeConnection", connectionId: id }).draft);
    setSelectedConnection(null);
    flash(false, id, t.draftRemoved);
  };

  // ---- Phase 7: navigation + page draft ops (skill 04 flow:
  // validate locally → draft → the adapter validates again on
  // apply → only then does state change → persistence). ----
  const draftNav = (change, label) => {
    snapshotHistory();
    const res = addChange(draft, change);
    if (!res.added) {
      flash(false, label, res.errors.join("; "));
      return;
    }
    setDraft(res.draft);
    flash(true, label, t.draftAdded);
  };

  const addNavItem = (item) => draftNav({ op: "addNavItem", item }, item.id);
  const moveNav = (navId, delta) => draftNav({ op: "moveNav", navId, delta }, navId);
  const toggleNavVisible = (navId, visible) =>
    draftNav({ op: "setNavVisibility", navId, visible }, navId);

  // Creating a page from a template yields TWO draft ops: the
  // page definition and its navigation entry.
  const createPage = (page, item) => {
    snapshotHistory();
    const r1 = addChange(draft, { op: "addPage", page });
    if (!r1.added) {
      flash(false, page.id, r1.errors.join("; "));
      return;
    }
    const r2 = addChange(r1.draft, { op: "addNavItem", item });
    if (!r2.added) {
      flash(false, item.id, r2.errors.join("; "));
      return;
    }
    setDraft(r2.draft);
    flash(true, item.id, t.draftAdded);
  };

  // ---- Phase 4: apply through the mock adapter contract ----
  // The adapter returns a per-operation result. A rejected
  // operation never produces a full-success message, and
  // rejected items stay in the draft with their reason.
  const applyDraft = async () => {
    if (applying) return;
    const pending = draft.changes.filter((c) => c.status === "pending");
    if (pending.length === 0) return;
    setApplying(true);
    try {
      const result = await adapter.applyChanges({
        base: { agents, connections: baseConnections, manifest, pages },
        changes: pending,
      });
      if (result && result.error) {
        // Typed adapter error — nothing was applied.
        flash(false, "apply", result.error.message);
        return;
      }
      snapshotHistory();
      setDraft((d) => applyResultsToDraft(d, result.results).draft);
      // The returned state contains ONLY accepted operations.
      setBaseConnections(result.connections);
      setAgents(result.agents);
      if (result.manifest) setManifest(result.manifest);
      if (result.pages) setPages(result.pages);
      setSelectedConnection(null);
      const rejected = result.results.filter((r) => r.status === "rejected").length;
      flash(
        rejected === 0,
        "apply",
        result.status === "ok"
          ? t.appliedOk
          : result.status === "partial"
            ? t.partiallyApplied
            : t.applyFailed
      );
    } finally {
      setApplying(false);
    }
  };

  // ---- Phase 4: workspace export / import / reset ----
  const handleExport = () => {
    const json = exportWorkspace({
      customTools: agents.filter((a) => a.custom),
      connections: baseConnections,
      view,
      manifest,
      pages,
    });
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `agent-os-workspace-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    flash(true, "export", t.exportOk);
  };

  const handleImport = (workspace) => {
    snapshotHistory();
    const existing = new Set(agents.map((a) => a.id));
    const fresh = workspace.customTools.filter((a) => !existing.has(a.id));
    const skipped = workspace.customTools.length - fresh.length;
    if (fresh.length) setAgents((prev) => [...prev, ...fresh]);
    if (workspace.connections) setBaseConnections(workspace.connections);
    if (workspace.view) setView(workspace.view);
    if (workspace.manifest) setManifest(workspace.manifest);
    if (workspace.pages) setPages(workspace.pages);
    flash(skipped === 0, "import", skipped === 0 ? t.importOk : t.importPartial);
  };

  const handleReset = (section) => {
    snapshotHistory();
    if (section === "layout") {
      setView((prev) => resetLayout(prev));
    } else {
      setAgents([...toAgents(seed.registry)]);
      setBaseConnections(seed.connections.list);
      setDraft(clearDraft());
      setSelectedConnection(null);
      if (section === "all") {
        setView((prev) => resetLayout(prev));
        setManifest(seed.manifest);
        setPages(seed.pages);
        setActiveRoute(HOME_ROUTE);
      }
    }
    flash(section === "layout", "reset", t.resetDone);
  };

  // ---- Phase 5: memory retrieval through the adapter.
  // Three separate facts: available connection, policy
  // grant, actual retrieval event. MOCK provider. ----
  const retrieve = async (agentId, scope) => {
    if (retrieving) return;
    setRetrieving(true);
    const seq = `${agentId}-${Date.now().toString(36)}`;
    setMemoryEvent({
      id: `${seq}-r`,
      from: agentId,
      to: memoryId,
      phase: "request",
    });
    // Simulated latency so the request pulse is visible.
    await new Promise((r) => setTimeout(r, 550));
    const res = await adapter.queryMemory({ agentId, scope, text: "" });
    const entry = {
      id: seq,
      agentId,
      scope,
      at: new Date().toTimeString().slice(0, 8),
    };
    if (res.ok) {
      setMemoryEvent({
        id: `${seq}-s`,
        from: agentId,
        to: memoryId,
        phase: "result",
        ok: true,
      });
      entry.status = "allowed";
      entry.count = res.items.length;
      setMemoryResult({
        ...entry,
        items: res.items,
        provider: res.provider,
        simulated: true,
      });
    } else {
      setMemoryEvent({
        id: `${seq}-s`,
        from: agentId,
        to: memoryId,
        phase: "result",
        ok: false,
      });
      entry.status = res.error.type === "access_denied" ? "denied" : "error";
      entry.error = res.error.message;
      setMemoryResult({ ...entry, items: [] });
    }
    setMemoryLog((l) => [entry, ...l].slice(0, 8));
    setRetrieving(false);
  };

  // Phase 0 fix (audit ISS-02): surface the adapter's four-fact capability so
  // the panel can explain an unsupported provider instead of showing a dead
  // Retrieve button that always errors (skill 08: unsupported is a declared
  // fact, shown WITH an explanation — never silently).
  const memorySupported = useMemo(
    () => adapter.getCapabilities().capabilities.queryMemory.supported,
    [adapter]
  );

  // Retrieval panel props for an agent with a
  // configured memory connection (null otherwise).
  const memoryPanelFor = (agentId) => {
    const conn = memoryConnections.find((c) => c.from === agentId);
    if (!conn) return null;
    return {
      connected: conn.state === "enabled",
      supported: memorySupported,
      scopes: seed.memory.scopes,
      granted: scopesForAgent(seed.memory.policy, agentId),
      retrieving,
      result:
        memoryResult && memoryResult.agentId === agentId ? memoryResult : null,
      onRetrieve: (scope) => retrieve(agentId, scope),
    };
  };

  // ---- Phase 6: clusters, timeline, replay ----
  const clusters = useMemo(() => buildClusters(seed.runtime), [seed]);

  // Group clusters by agent (an agent may own several
  // parent runs); counts aggregate across them.
  const clusterViews = useMemo(() => {
    const byAgent = new Map();
    for (const cl of clusters) {
      const v =
        byAgent.get(cl.agentId) || {
          agentId: cl.agentId,
          freshness: cl.freshness,
          counts: { total: 0, active: 0, waiting: 0, failed: 0, succeeded: 0 },
          parentRunIds: [],
        };
      for (const k of ["total", "active", "waiting", "failed", "succeeded"]) {
        v.counts[k] += cl.counts[k];
      }
      v.parentRunIds.push(cl.parentRunId);
      byAgent.set(cl.agentId, v);
    }
    return [...byAgent.values()];
  }, [clusters]);

  // Subtrees for expanded clusters: [{ run, depth }].
  const expandedSubtrees = useMemo(() => {
    const out = {};
    for (const v of clusterViews) {
      if (!expandedClusters.has(v.agentId)) continue;
      const rows = [];
      for (const pid of v.parentRunIds) {
        rows.push(...runSubtree(seed.runtime, pid));
      }
      out[v.agentId] = rows;
    }
    return out;
  }, [clusterViews, expandedClusters, seed]);

  const toggleCluster = (agentId) => {
    setExpandedClusters((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  };

  // Run selection syncs the canvas and the Inspector.
  const selectRun = (runId) => {
    if (runId == null) {
      setSelectedRun(null);
      return;
    }
    const run = getRun(seed.runtime, runId);
    if (!run) return;
    setSelectedRun(runId);
    setSelected(run.agentId);
  };

  const selectedRunRecord = selectedRun
    ? getRun(seed.runtime, selectedRun)
    : null;

  // Replay events in occurredAt/sequence order.
  const replayEvents = useMemo(
    () =>
      [...seed.runtime.events].sort(
        (a, b) =>
          a.occurredAt - b.occurredAt || (a.sequence ?? 0) - (b.sequence ?? 0)
      ),
    [seed]
  );

  // Workspace context for declarative page renderers (skill 07).
  const pageCtx = useMemo(
    () => ({
      agents,
      connections,
      kinds,
      runtime: seed.runtime,
      manifest,
      pages,
      models: seed.models,
      // Real backend adapter + connection state for the backend-live renderer.
      backend: { adapter: agentOs, status: connectionState, live: backendLive },
    }),
    [agents, connections, kinds, seed, manifest, pages, agentOs, connectionState, backendLive]
  );

  const onDiscard = () => {
    snapshotHistory();
    setDraft(clearDraft());
    setSelectedConnection(null);
  };

  const undoChange = () => {
    const res = undo(changeHistory, { draft, view });
    if (!res.snapshot) return;
    setChangeHistory(res.history);
    setDraft(res.snapshot.draft);
    setView(res.snapshot.view);
  };

  const redoChange = () => {
    const res = redo(changeHistory, { draft, view });
    if (!res.snapshot) return;
    setChangeHistory(res.history);
    setDraft(res.snapshot.draft);
    setView(res.snapshot.view);
  };

  const resetLayoutView = () => {
    snapshotHistory();
    setView((prev) => resetLayout(prev));
  };

  // Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      const k = e.key.toLowerCase();
      if (k === "z") {
        e.preventDefault();
        if (e.shiftKey) redoChange();
        else undoChange();
      } else if (k === "y") {
        e.preventDefault();
        redoChange();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Phase 4: load the persisted workspace once. Every
  // section is validated; malformed data keeps its
  // default and is reported — never a crash.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const loaded = await loadWorkspace(storage, { registry: seed.registry });
      if (cancelled) return;
      if (loaded.customTools.length) {
        // Defensive dedupe by id: append only tools that are not already
        // present, so a re-run of this effect (or a future StrictMode
        // double-mount) can never duplicate a persisted tool.
        setAgents((prev) => {
          const seen = new Set(prev.map((a) => a.id));
          const fresh = loaded.customTools.filter((a) => !seen.has(a.id));
          return fresh.length ? [...prev, ...fresh] : prev;
        });
      }
      if (loaded.connections) setBaseConnections(loaded.connections);
      if (loaded.view) setView(loaded.view);
      if (loaded.manifest) setManifest(loaded.manifest);
      if (loaded.pages) setPages(loaded.pages);
      if (loaded.errors.length) setBootErrors(loaded.errors);
      setBoot("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, [seed, storage]);

  // Phase 4: persist non-secret workspace config (debounced).
  // Gated on boot so a save never clobbers stored data
  // before it is loaded. Browser storage is LOCAL —
  // not multi-user persistence.
  useEffect(() => {
    if (boot !== "ready") return;
    const iv = setTimeout(() => {
      saveWorkspace(storage, {
        customTools: agents.filter((a) => a.custom),
        connections: baseConnections,
        view,
        manifest,
        pages,
      });
    }, 300);
    return () => clearTimeout(iv);
  }, [boot, storage, agents, baseConnections, view, manifest, pages]);

  // Keep the adapter's resource index in sync for
  // listResources / getResource.
  useEffect(() => {
    adapter.syncWorkspace({ agents, connections });
  }, [adapter, agents, connections]);

  // Runtime event replay (observational only — it
  // never triggers tools or config changes).
  useEffect(() => {
    if (!playing) return;
    const iv = setInterval(
      () =>
        setCursor((c) => {
          const next = c === null ? 0 : c + 1;
          return next >= replayEvents.length ? (setPlaying(false), null) : next;
        }),
      900
    );
    return () => clearInterval(iv);
  }, [playing, replayEvents.length]);

  const replayEvent = cursor !== null ? replayEvents[cursor] : null;
  const replayAgent = replayEvent?.agentId || null;
  useEffect(() => {
    replayAgent && fire(replayAgent);
  }, [cursor]);

  const focusId = selected || replayAgent;
  const focused = agents.find((a) => a.id === focusId);

  const addTool = (a) => {
    setAgents((list) => [...list, a]);
    setAdding(false);
    setSelected(a.id);
    flash(true, a.name, t.launched);
    setTimeout(() => fire(a.id), 200);
  };

  const removeTool = (id) => {
    const a = agents.find((x) => x.id === id);
    setAgents((list) => list.filter((x) => x.id !== id && x.parent !== id));
    setSelected(null);
    flash(false, a?.name, t.removed);
  };

  const decide = (g, ok) => {
    setAgents((list) =>
      list.map((a) => (a.id === g.agent ? { ...a, status: ok ? (g.agent === "wordpress" ? "complete" : "running") : "offline" } : a))
    );
    setApprovals((q) => q.filter((x) => x.id !== g.id));
    flash(ok, g.id);
    ok && fire(g.agent);
  };

  const counts = useMemo(() => {
    const c = { running: 0, awaiting: 0, complete: 0, offline: 0 };
    agents.forEach((a) => c[a.status]++);
    return c;
  }, [agents]);

  const labelFor = (a) => (
    <div className={rtl ? "f-fa" : "f-en"}>
      <b>
        {a.name}
        {kinds[a.id] === "memory" && <span className="mock-tag">MOCK</span>}
      </b>
      <small>{a.sub[lang]}</small>
      <span className="st" style={{ color: STATUS_COLOR[a.status] }}>
        <i style={{ background: STATUS_COLOR[a.status] }} />
        {t.legend[a.status]}
      </span>
    </div>
  );

  const coreLabel = (
    <span className={rtl ? "f-fa" : "f-en"}>
      <Brain size={16} />
      <em>Hermes</em>
      {"· "}
      {t.brain}
    </span>
  );

  // If the workspace model fails validation, show an explicit error
  // state — never fall back to demo data silently.
  if (seed.errors.length) {
    return (
      <div dir={rtl ? "rtl" : "ltr"} className={`deck text-[15px] ${rtl ? "f-fa" : "f-en"}`}>
        <div className="glass m-4 p-6">
          <h2 className="disp text-[20px] text-[#ff5c7a]">
            {rtl ? "خطا در بارگذاری مدل فضای کاری" : "Workspace model error"}
          </h2>
          <p className="mono mt-3 whitespace-pre-wrap text-[14px] text-[var(--mu)]">
            {seed.errors.join("\n")}
          </p>
        </div>
      </div>
    );
  }

  // Draft controls are GLOBAL: the same DraftBar instance lives in
  // the command-canvas toolbar AND on every routed page. The draft
  // flow (review → apply → persist, skill 04) must stay complete
  // regardless of the active route (skill 07).
  const draftBarNode = (
    <DraftBar
      t={t}
      mode={mode}
      onMode={setMode}
      summary={summary}
      hasPending={hasPending}
      canUndo={changeHistory.past.length > 0}
      canRedo={changeHistory.future.length > 0}
      onUndo={undoChange}
      onRedo={redoChange}
      onApply={applyDraft}
      onDiscard={onDiscard}
      applying={applying}
    />
  );

  // Export / import / reset are GLOBAL like the draft bar (phase 8,
  // audit finding 2): they must stay reachable on every routed page,
  // not only on the command canvas.
  const workspaceToolsNode = (
    <WorkspaceTools
      t={t}
      onExport={handleExport}
      onImport={handleImport}
      onReset={handleReset}
      parseContext={{ registry: seed.registry }}
    />
  );

  return (
    <div dir={rtl ? "rtl" : "ltr"} className={`deck text-[15px] ${rtl ? "f-fa" : "f-en"}`}>
      <Header t={t} lang={lang} setLang={setLang} />
      <div className="grid grid-cols-1 gap-4 p-4 [&>*]:min-w-0 lg:grid-cols-[210px_1fr_370px] lg:grid-rows-[minmax(700px,1fr)_auto]">
        <Sidebar
          t={t}
          lang={lang}
          manifest={manifest}
          activeRoute={activeRoute}
          onNavigate={setActiveRoute}
          capabilities={capabilities}
          permissions={GRANTED_PERMISSIONS}
          badges={{ missions: approvals.length, agents: counts.running }}
          onCustomize={() => setCustomizingNav(true)}
        />
        {activeRoute === HOME_ROUTE ? (
          <>
        <section className="glass hud-frame relative flex min-h-[700px] flex-col overflow-hidden">
          <div className="relative z-10 flex flex-wrap items-end gap-x-4 gap-y-1 px-6 pt-5">
            <h2 className="disp text-[32px] leading-none text-[var(--sun2)]" style={{ textShadow: "0 0 18px rgba(56,232,255,.45)" }}>
              {t.graph}
            </h2>
            <span className="pb-0.5 text-[15px] text-[var(--mu)]">{t.graphSub}</span>
            <span className="mono ms-auto pb-0.5 text-[14px] text-[var(--mu)]">wp-bioscentiran</span>
          </div>
          <div className="relative z-10 flex flex-wrap gap-2 px-6 pt-4">
            <label className="flex min-w-[220px] flex-1 items-center gap-2 rounded-full border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-4 py-2">
              <Search size={16} className="text-[var(--mu)]" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t.search}
                className="w-full bg-transparent text-[15px] outline-none"
              />
            </label>
            <button
              onClick={() => setAdding(true)}
              className="btn-core flex items-center gap-2 rounded-full px-4 py-2 text-[14px] font-semibold transition hover:brightness-110"
            >
              <Cable size={16} />
              {t.add}
            </button>
            <Btn icon={SlidersHorizontal}>{t.filter}</Btn>
            <Btn
              icon={Crosshair}
              onClick={() => {
                setQuery("");
                setSelected(null);
                setCursor(null);
              }}
            >
              {t.refresh}
            </Btn>
            {mode === "edit" && (
              <Btn icon={LayoutGrid} onClick={resetLayoutView}>
                {t.resetLayout}
              </Btn>
            )}
            <div className="ms-auto flex items-center gap-2">
              {draftBarNode}
              {workspaceToolsNode}
            </div>
          </div>
          <div className="relative mt-2 min-h-[500px] flex-1" dir="ltr">
            <NeuralScene
              agents={agents}
              connections={connections}
              selected={selected}
              setSelected={setSelected}
              highlight={replayAgent}
              query={query}
              labelFor={labelFor}
              coreLabel={coreLabel}
              burst={burst}
              rtl={rtl}
              view={view}
              onViewChange={setView}
              onViewSnapshot={snapshotHistory}
              kinds={kinds}
              coordinatorId={coordinatorId}
              registry={seed.registry}
              mode={mode}
              selectedConnection={selectedConnection}
              setSelectedConnection={setSelectedConnection}
              onProposeConnection={proposeConnection}
              onDisconnectConnection={disconnectConnection}
              connectFrom={connectFrom}
              setConnectFrom={setConnectFrom}
              strings={t}
              flash={flash}
              memoryEvent={memoryEvent}
              clusters={clusterViews}
              expandedClusters={expandedClusters}
              subtrees={expandedSubtrees}
              onToggleCluster={toggleCluster}
              onSelectRun={selectRun}
              selectedRun={selectedRun}
            />
            {bootErrors.length > 0 && (
              <div className="glass absolute bottom-3 end-3 z-40 max-w-[320px] p-3">
                <div className="text-[13px] font-semibold text-[#ffd166]">
                  {t.storageErrors}
                </div>
                <ul className="mt-1.5 flex flex-col gap-1 text-[12px] text-[var(--mu)]">
                  {bootErrors.map((e, i) => (
                    <li key={`be-${i}`}>• {e}</li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={() => setBootErrors([])}
                  className="chip mt-2 w-full justify-center"
                >
                  {t.dismiss}
                </button>
              </div>
            )}
            {focused && memoryId && focused.id === memoryId && (
              <MemoryInspector
                t={t}
                providerName={seed.memory.providerName}
                connections={memoryConnections}
                policy={seed.memory.policy}
                log={memoryLog}
                lastResult={memoryResult}
                onClose={() => {
                  setSelected(null);
                  setCursor(null);
                }}
              />
            )}
            {focused && (!memoryId || focused.id !== memoryId) && (
              <StatusCard
                key={focused.id}
                a={focused}
                t={t}
                rtl={rtl}
                lang={lang}
                mode={mode}
                onConnect={() => setConnectFrom(focused.id)}
                onClose={() => {
                  setSelected(null);
                  setCursor(null);
                }}
                onRemove={focused.custom ? () => removeTool(focused.id) : null}
                memory={memoryPanelFor(focused.id)}
                run={
                  selectedRunRecord && selectedRunRecord.agentId === focused.id
                    ? selectedRunRecord
                    : null
                }
                freshness={subagentFreshness(seed.runtime, focused.id)}
              />
            )}
            {adding && <AddTool t={t} rtl={rtl} agents={agents} onCancel={() => setAdding(false)} onAdd={addTool} />}
          </div>
          <div className="relative z-10 flex flex-wrap items-stretch gap-3 px-5 pb-4">
            <div className="glass px-4 py-3">
              <div className="text-[14px] text-[var(--mu)]">{t.statusTitle}</div>
              <div className="mt-1.5 flex items-center gap-3">
                {Object.keys(counts).map((s) => (
                  <span key={s} className="flex items-center gap-1.5" title={t.legend[s]}>
                    <i className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS_COLOR[s], boxShadow: `0 0 8px ${STATUS_COLOR[s]}` }} />
                    <span className="mono text-[14px]">{counts[s]}</span>
                  </span>
                ))}
              </div>
            </div>
            <div className="glass px-4 py-3">
              <div className="text-[14px] text-[var(--mu)]">{t.lastRun}</div>
              <div className="mt-1.5 flex items-center gap-2">
                <i className="h-2 w-2 rounded-full bg-[var(--sun)]" style={{ boxShadow: "0 0 8px #38e8ff" }} />
                <span className="mono text-[14px]">wp-bioscentiran · 17:46:02</span>
              </div>
            </div>
            <div className="ms-auto flex flex-wrap items-center gap-x-4 gap-y-1 self-end pb-1 text-[14px] text-[var(--mu)]">
              {Object.keys(t.legend).map((s) => (
                <span key={s} className="flex items-center gap-2">
                  <i className="h-[3px] w-5 rounded-full" style={{ background: STATUS_COLOR[s], boxShadow: `0 0 8px ${STATUS_COLOR[s]}` }} />
                  {t.legend[s]}
                </span>
              ))}
            </div>
          </div>
        </section>
        <Gate approvals={approvals} t={t} lang={lang} decide={decide} />
        <Timeline
          t={t}
          lang={lang}
          rtl={rtl}
          store={seed.runtime}
          agents={agents}
          selectedRun={selectedRun}
          onSelectRun={selectRun}
          cursor={cursor}
          setCursor={(c) => {
            setCursor(c);
            setSelected(null);
          }}
          playing={playing}
          setPlaying={setPlaying}
          missionFilter={missionFilter}
          setMissionFilter={setMissionFilter}
          activeOnly={activeOnly}
          setActiveOnly={setActiveOnly}
          replayEvents={replayEvents}
        />
          </>
        ) : (
          <PageRouter
            route={activeRoute}
            manifest={manifest}
            pages={pages}
            t={t}
            lang={lang}
            rtl={rtl}
            ctx={pageCtx}
            draftBar={draftBarNode}
            tools={workspaceToolsNode}
            onNavigate={setActiveRoute}
          />
        )}
      </div>
      {toast && (
        <div
          className="rise glass fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 px-4 py-2.5"
          style={{ borderColor: toast.ok ? "rgba(95,240,168,.5)" : "rgba(255,92,122,.5)" }}
        >
          {toast.ok ? <Check size={16} color="#5ff0a8" /> : <X size={16} color="#ff5c7a" />}
          <span className="mono text-[14px]">{toast.id}</span>
          <span>{toast.msg || (toast.ok ? t.approved : t.rejected)}</span>
        </div>
      )}
      {customizingNav && (
        <NavCustomizer
          t={t}
          lang={lang}
          manifest={manifest}
          pages={pages}
          onAddNavItem={addNavItem}
          onMoveNav={moveNav}
          onToggleVisible={toggleNavVisible}
          onCreatePage={createPage}
          onClose={() => setCustomizingNav(false)}
        />
      )}
    </div>
  );
}
