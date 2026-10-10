// Provider-neutral execution event contract + testable reducer (pure).
//
// Every execution (mission run, subagent run, memory query) is
// identified by its own runId — never by an agent display name.
// The reducer is a pure function: dedupe by eventId, order by
// occurredAt/sequence, never overwrite newer state with an older
// event, handle snapshots, and keep telemetry freshness separate
// from execution state.

export const EVENT_TYPES = [
  "run.created",
  "run.started",
  "run.activity",
  "run.waiting",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "memory.query.started",
  "memory.query.completed",
  "memory.query.failed",
];

export const RUN_STATES = ["queued", "running", "waiting", "succeeded", "failed", "cancelled"];

export const WAITING_REASONS = ["approval", "tool", "dependency", "user input"];

export const TELEMETRY_LEVELS = ["full", "partial", "unavailable"];

export const TERMINAL_RUN_STATES = ["succeeded", "failed", "cancelled"];

const STATE_EVENTS = {
  "run.created": "queued",
  "run.started": "running",
  "run.waiting": "waiting",
  "run.completed": "succeeded",
  "run.failed": "failed",
  "run.cancelled": "cancelled",
};

const isNum = (n) => typeof n === "number" && Number.isFinite(n);

/**
 * Validate one event. Optional fields are tolerated; required fields
 * are enforced. Never throws.
 * @returns {{ok:boolean, errors:string[]}}
 */
export function validateEvent(event) {
  const errors = [];
  if (!event || typeof event !== "object") {
    return { ok: false, errors: ["event must be an object"] };
  }
  if (typeof event.eventId !== "string" || event.eventId.length === 0) {
    errors.push("eventId is required (non-empty string)");
  }
  if (typeof event.runId !== "string" || event.runId.length === 0) {
    errors.push("runId is required (non-empty string)");
  }
  if (typeof event.agentId !== "string" || event.agentId.length === 0) {
    errors.push("agentId is required (non-empty string)");
  }
  if (!EVENT_TYPES.includes(event.type)) {
    errors.push(`unknown event type: ${String(event.type)}`);
  }
  if (!isNum(event.occurredAt)) {
    errors.push("occurredAt is required (finite epoch milliseconds)");
  }
  if (event.sequence != null && (!Number.isInteger(event.sequence) || event.sequence < 0)) {
    errors.push("sequence must be a non-negative integer when present");
  }
  if (event.type === "run.waiting" && !WAITING_REASONS.includes(event.waitingReason)) {
    errors.push(`run.waiting requires waitingReason one of: ${WAITING_REASONS.join(", ")}`);
  }
  if (event.error != null && typeof event.error !== "string") {
    errors.push("error must be a string when present");
  }
  if (event.artifactRefs != null && !Array.isArray(event.artifactRefs)) {
    errors.push("artifactRefs must be an array when present");
  }
  return { ok: errors.length === 0, errors };
}

/** Initial execution store. `source` labels data truthfulness
 * ("demo" | "mock" | "live:<adapterId>"). */
export function createExecutionStore(source = "unknown") {
  return {
    source,
    runs: {}, // runId -> run record
    missions: {}, // missionId -> { missionId, runIds }
    events: [], // applied events in applied order
    seenEventIds: {}, // dedupe set
    retrievals: [], // memory query records, keyed by runId
    telemetry: {}, // agentId -> telemetry support level
    freshness: {}, // agentId -> subagent telemetry freshness
  };
}

// An event is stale when it is strictly older than the run's latest
// applied event (by occurredAt, then sequence).
function isStale(run, event) {
  const last = run.lastEvent;
  if (!last) return false;
  if (event.occurredAt < last.occurredAt) return true;
  if (
    event.occurredAt === last.occurredAt &&
    event.sequence != null &&
    last.sequence != null &&
    event.sequence <= last.sequence
  ) {
    return true;
  }
  return false;
}

/**
 * Apply one event to the store. Pure.
 * - duplicate eventId -> rejected
 * - stale (older) event -> rejected
 * - terminal runs ignore further state transitions (the event itself
 *   is still recorded in the log)
 * @returns {{store:Object, applied:boolean, errors:string[]}}
 */
export function reduceEvent(store, rawEvent) {
  const check = validateEvent(rawEvent);
  if (!check.ok) return { store, applied: false, errors: check.errors };
  const event = { ...rawEvent };

  if (store.seenEventIds[event.eventId]) {
    return { store, applied: false, errors: [`duplicate eventId: ${event.eventId}`] };
  }
  const run = store.runs[event.runId];
  if (run && isStale(run, event)) {
    return {
      store,
      applied: false,
      errors: [`stale event ignored (older than the run's latest applied event): ${event.eventId}`],
    };
  }

  const next = {
    ...store,
    runs: { ...store.runs },
    missions: { ...store.missions },
    events: [...store.events, event],
    seenEventIds: { ...store.seenEventIds, [event.eventId]: true },
  };

  // ---- memory query events -> retrieval records ----
  if (event.type.startsWith("memory.query.")) {
    const prev = store.retrievals.find((r) => r.runId === event.runId) || {};
    const state =
      event.type === "memory.query.started"
        ? "in-flight"
        : event.type === "memory.query.completed"
          ? "succeeded"
          : "failed";
    next.retrievals = [
      ...store.retrievals.filter((r) => r.runId !== event.runId),
      {
        runId: event.runId,
        missionId: event.missionId || prev.missionId || null,
        agentId: event.agentId,
        scope: event.scope || prev.scope || null,
        state,
        startedAt: prev.startedAt || event.occurredAt,
        endedAt: state === "in-flight" ? null : event.occurredAt,
        error: event.error || prev.error || null,
        lastEventId: event.eventId,
      },
    ];
    return { store: next, applied: true, errors: [] };
  }

  // ---- run events ----
  const newState = STATE_EVENTS[event.type];
  let runNext;
  if (!run) {
    runNext = {
      runId: event.runId,
      missionId: event.missionId || null,
      agentId: event.agentId,
      parentRunId: event.parentRunId || null,
      assignedTask: event.assignedTask || null,
      state: "queued",
      stateHistory: [{ state: "queued", at: event.occurredAt, eventId: event.eventId }],
      activity: [],
      artifacts: [],
      waitingReason: null,
      error: null,
      startedAt: null,
      endedAt: null,
      lastEvent: null,
    };
  } else {
    runNext = {
      ...run,
      // Snapshot records from real adapters may be partial —
      // never assume the internal arrays exist.
      stateHistory: Array.isArray(run.stateHistory) ? [...run.stateHistory] : [],
      activity: Array.isArray(run.activity) ? [...run.activity] : [],
      artifacts: Array.isArray(run.artifacts) ? [...run.artifacts] : [],
    };
  }

  if (newState && !TERMINAL_RUN_STATES.includes(runNext.state)) {
    // A terminal run never changes state again. State transitions
    // are idempotent: repeating the same state is a no-op, but
    // a waiting reason is still refreshed.
    if (runNext.state !== newState) {
      runNext.state = newState;
      runNext.stateHistory.push({ state: newState, at: event.occurredAt, eventId: event.eventId });
      if (event.type === "run.started") runNext.startedAt = event.occurredAt;
      if (TERMINAL_RUN_STATES.includes(newState)) runNext.endedAt = event.occurredAt;
    }
    runNext.waitingReason = event.type === "run.waiting" ? event.waitingReason || null : null;
    if (event.type === "run.failed") runNext.error = event.error || "run failed";
  }

  if (event.type === "run.activity") {
    runNext.activity.push({ at: event.occurredAt, text: event.reportedActivity || "" });
  }
  if (event.artifactRefs && event.artifactRefs.length > 0) {
    runNext.artifacts.push(...event.artifactRefs);
  }

  runNext.lastEvent = {
    occurredAt: event.occurredAt,
    sequence: event.sequence != null ? event.sequence : null,
    eventId: event.eventId,
  };
  next.runs[event.runId] = runNext;

  const missionId = event.missionId || "unknown";
  const mission = next.missions[missionId] || { missionId, runIds: [] };
  if (!mission.runIds.includes(event.runId)) mission.runIds.push(event.runId);
  next.missions[missionId] = mission;

  return { store: next, applied: true, errors: [] };
}

/** Apply events in order; returns per-event results. */
export function applyEvents(store, events) {
  let cur = store;
  const results = [];
  for (const ev of events) {
    const res = reduceEvent(cur, ev);
    cur = res.store;
    results.push({ eventId: ev.eventId, applied: res.applied, errors: res.errors });
  }
  return { store: cur, results };
}

// ---- Selectors ----

export function getRun(store, runId) {
  return store.runs[runId] || null;
}

/** Child/subagent runs of a parent run (by parentRunId). */
export function childRuns(store, runId) {
  return Object.values(store.runs).filter((r) => r.parentRunId === runId);
}

export function runsForAgent(store, agentId) {
  return Object.values(store.runs).filter((r) => r.agentId === agentId);
}

export function runsForMission(store, missionId) {
  const m = store.missions[missionId];
  if (!m) return [];
  return m.runIds.map((id) => store.runs[id]).filter(Boolean);
}

/**
 * Mission summary counts. "finished" (terminal) and "succeeded" are
 * reported separately: "2 of 3 runs finished" != "2 of 3 succeeded".
 */
export function missionCounts(store, missionId) {
  const runs = runsForMission(store, missionId);
  const counts = {
    total: runs.length,
    finished: 0,
    succeeded: 0,
    failed: 0,
    cancelled: 0,
    running: 0,
    waiting: 0,
    queued: 0,
  };
  for (const r of runs) {
    if (TERMINAL_RUN_STATES.includes(r.state)) counts.finished += 1;
    if (r.state === "succeeded") counts.succeeded += 1;
    if (r.state === "failed") counts.failed += 1;
    if (r.state === "cancelled") counts.cancelled += 1;
    if (r.state === "running") counts.running += 1;
    if (r.state === "waiting") counts.waiting += 1;
    if (r.state === "queued") counts.queued += 1;
  }
  return counts;
}

/** Telemetry support level for an agent. Default is "unavailable" —
 * the honest default: absence of data is never reported as fact. */
export function telemetryLevel(store, agentId) {
  return store.telemetry[agentId] || "unavailable";
}

export function setTelemetryLevel(store, agentId, level) {
  if (!TELEMETRY_LEVELS.includes(level)) {
    return { store, errors: [`unknown telemetry level: ${level}`] };
  }
  return {
    store: { ...store, telemetry: { ...store.telemetry, [agentId]: level } },
    errors: [],
  };
}

/**
 * Reconnection snapshot: wholesale replacement of runs/missions/events.
 * Late events applied after the snapshot still dedupe and order correctly.
 */
export function applySnapshot(store, snapshot) {
  const errors = [];
  if (!snapshot || typeof snapshot !== "object") {
    return { store, errors: ["snapshot must be an object"] };
  }
  if (!snapshot.runs || typeof snapshot.runs !== "object") {
    errors.push("snapshot.runs is required");
  }
  if (!Array.isArray(snapshot.events)) {
    errors.push("snapshot.events is required");
  }
  if (errors.length) return { store, errors };
  const seenEventIds = {};
  for (const ev of snapshot.events) {
    if (ev && typeof ev.eventId === "string") seenEventIds[ev.eventId] = true;
  }
  const next = {
    source: store.source,
    runs: snapshot.runs,
    missions: snapshot.missions && typeof snapshot.missions === "object" ? snapshot.missions : {},
    events: snapshot.events,
    seenEventIds,
    retrievals: Array.isArray(snapshot.retrievals) ? snapshot.retrievals : [],
    telemetry: store.telemetry,
    freshness: store.freshness,
  };
  return { store: next, errors: [] };
}

// ---- Skill 06: freshness, clusters, timeline helpers ----

export const FRESHNESS_LEVELS = ["fresh", "stale", "unavailable"];

/** Subagent telemetry freshness for an agent. Default
 *  "unavailable" — absence of subagent data is never
 *  reported as an established zero. */
export function subagentFreshness(store, agentId) {
  return store.freshness?.[agentId] || "unavailable";
}

export function setSubagentFreshness(store, agentId, level) {
  if (!FRESHNESS_LEVELS.includes(level)) {
    return { store, errors: [`unknown freshness level: ${level}`] };
  }
  return {
    store: { ...store, freshness: { ...store.freshness, [agentId]: level } },
    errors: [],
  };
}

/** A run is active while it has not reached a
 *  terminal state. */
export function isRunActive(run) {
  return !!run && !TERMINAL_RUN_STATES.includes(run.state);
}

/** Time interval a run occupies: started -> ended
 *  (or its latest known event while still active). */
export function runInterval(run) {
  if (!run) return null;
  const start = run.startedAt ?? run.stateHistory?.[0]?.at ?? null;
  const end = run.endedAt ?? run.lastEvent?.occurredAt ?? null;
  return { start, end };
}

/** True when two run intervals overlap in time
 *  (concurrent execution). An open-ended active
 *  run (end == null) overlaps everything after
 *  its start. */
export function intervalsOverlap(a, b) {
  if (!a || !b || a.start == null || b.start == null) return false;
  const aEnd = a.end ?? Number.POSITIVE_INFINITY;
  const bEnd = b.end ?? Number.POSITIVE_INFINITY;
  return a.start < bEnd && b.start < aEnd;
}

/** Waiting segments of a run, derived from its
 *  state history: each "waiting" entry lasts until
 *  the next state entry (or the run's end). */
export function waitingSegments(run) {
  const segs = [];
  const hist = Array.isArray(run?.stateHistory) ? run.stateHistory : [];
  for (let i = 0; i < hist.length; i += 1) {
    if (hist[i].state !== "waiting") continue;
    const next = hist[i + 1];
    segs.push({
      from: hist[i].at,
      to: next ? next.at : (run.endedAt ?? run.lastEvent?.occurredAt ?? null),
    });
  }
  return segs;
}

/** Milliseconds a run has occupied so far (null
 *  when it never started). */
export function elapsedMs(run) {
  if (!run || run.startedAt == null) return null;
  const end = run.endedAt ?? run.lastEvent?.occurredAt ?? run.startedAt;
  return Math.max(0, end - run.startedAt);
}

/** Counts over a set of runs. "active" (non-terminal)
 *  is reported separately from "succeeded". */
export function runCounts(runs) {
  const counts = {
    total: runs.length,
    active: 0,
    running: 0,
    queued: 0,
    waiting: 0,
    succeeded: 0,
    failed: 0,
    cancelled: 0,
  };
  for (const r of runs) {
    if (isRunActive(r)) counts.active += 1;
    if (r.state === "running") counts.running += 1;
    if (r.state === "queued") counts.queued += 1;
    if (r.state === "waiting") counts.waiting += 1;
    if (r.state === "succeeded") counts.succeeded += 1;
    if (r.state === "failed") counts.failed += 1;
    if (r.state === "cancelled") counts.cancelled += 1;
  }
  return counts;
}

/**
 * Subagent clusters (skill 06): parent runs whose
 * children were reported. Agents whose provider has
 * NO subagent telemetry are EXCLUDED — the UI then
 * shows "Subagent telemetry unavailable" instead of
 * an established zero.
 */
export function buildClusters(store) {
  const parents = new Set();
  for (const r of Object.values(store.runs || {})) {
    if (r && r.parentRunId) parents.add(r.parentRunId);
  }
  const clusters = [];
  for (const parentRunId of parents) {
    const parent = store.runs[parentRunId];
    if (!parent) continue;
    const freshness = subagentFreshness(store, parent.agentId);
    if (freshness === "unavailable") continue;
    clusters.push({
      parentRunId,
      agentId: parent.agentId,
      freshness,
      counts: runCounts(childRuns(store, parentRunId)),
    });
  }
  return clusters;
}

/** Flatten a run's subtree: [{ run, depth }], parent
 *  first, descendants indented by depth. Drives the
 *  expanded cluster and the timeline nesting. */
export function runSubtree(store, runId, depth = 0) {
  const run = store.runs?.[runId];
  if (!run) return [];
  const rows = [{ run, depth }];
  for (const child of childRuns(store, runId)) {
    rows.push(...runSubtree(store, child.runId, depth + 1));
  }
  return rows;
}

/** All runs ordered by start time (then runId). */
export function runsInOrder(store) {
  return Object.values(store.runs || [])
    .filter(Boolean)
    .sort((a, b) => {
      const sa = runInterval(a)?.start ?? Number.POSITIVE_INFINITY;
      const sb = runInterval(b)?.start ?? Number.POSITIVE_INFINITY;
      return sa - sb || (a.runId < b.runId ? -1 : 1);
    });
}

/** Mission ids present in the store, ordered. */
export function missionList(store) {
  return Object.keys(store.missions || {}).sort();
}

/** Nesting depth of a run (0 = top-level). */
export function depthOfRun(store, runId) {
  let depth = 0;
  let cur = store.runs?.[runId];
  const guard = new Set();
  while (cur && cur.parentRunId && !guard.has(cur.runId)) {
    guard.add(cur.runId);
    depth += 1;
    cur = store.runs[cur.parentRunId];
  }
  return depth;
}
