import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createExecutionStore,
  reduceEvent,
  applyEvents,
  validateEvent,
  getRun,
  childRuns,
  runsForAgent,
  missionCounts,
  telemetryLevel,
  setTelemetryLevel,
  applySnapshot,
} from "../src/model/runtime.js";

const T0 = 1_700_000_000_000;

// Unique eventIds by default; tests that need a collision
// pass an explicit eventId.
let eventCounter = 0;
function mkEvent(over = {}) {
  eventCounter += 1;
  return {
    eventId: `e${eventCounter}`,
    sequence: 0,
    occurredAt: T0,
    receivedAt: T0,
    missionId: "m1",
    runId: "r1",
    agentId: "a1",
    type: "run.created",
    ...over,
  };
}

test("validateEvent enforces required fields and waiting reasons", () => {
  assert.equal(validateEvent(mkEvent()).ok, true);
  assert.equal(validateEvent({}).ok, false);
  assert.equal(validateEvent(mkEvent({ type: "run.tp" })).ok, false);
  assert.equal(validateEvent(mkEvent({ occurredAt: "soon" })).ok, false);
  assert.equal(validateEvent(mkEvent({ type: "run.waiting" })).ok, false);
  assert.equal(
    validateEvent(mkEvent({ type: "run.waiting", waitingReason: "approval" })).ok,
    true
  );
});

test("full run lifecycle", () => {
  const { store } = applyEvents(createExecutionStore("mock"), [
    mkEvent(),
    mkEvent({ type: "run.started", sequence: 1, occurredAt: T0 + 1 }),
    mkEvent({ type: "run.activity", sequence: 2, occurredAt: T0 + 2, reportedActivity: "working" }),
    mkEvent({ type: "run.completed", sequence: 3, occurredAt: T0 + 3 }),
  ]);
  const run = getRun(store, "r1");
  assert.equal(run.state, "succeeded");
  assert.equal(run.activity.length, 1);
  assert.equal(run.activity[0].text, "working");
  assert.ok(run.startedAt <= run.endedAt);
  assert.equal(run.stateHistory.length, 3); // queued -> running -> succeeded
});

test("waiting records the reason separately from state", () => {
  const { store } = applyEvents(createExecutionStore(), [
    mkEvent(),
    mkEvent({ type: "run.waiting", sequence: 1, occurredAt: T0 + 1, waitingReason: "dependency" }),
  ]);
  const run = getRun(store, "r1");
  assert.equal(run.state, "waiting");
  assert.equal(run.waitingReason, "dependency");
});

test("terminal runs ignore later state transitions but keep the event in the log", () => {
  const { store } = applyEvents(createExecutionStore(), [
    mkEvent(),
    mkEvent({ type: "run.completed", sequence: 1, occurredAt: T0 + 1 }),
    mkEvent({ type: "run.started", sequence: 2, occurredAt: T0 + 2 }),
  ]);
  assert.equal(getRun(store, "r1").state, "succeeded");
  assert.equal(store.events.length, 3);
});

test("duplicate eventId is rejected", () => {
  const r1 = reduceEvent(createExecutionStore(), mkEvent({ eventId: "dup-1" }));
  const r2 = reduceEvent(r1.store, mkEvent({ eventId: "dup-1" }));
  assert.equal(r1.applied, true);
  assert.equal(r2.applied, false);
});

test("older events never overwrite newer state", () => {
  const { store } = applyEvents(createExecutionStore(), [
    mkEvent({ sequence: 0, occurredAt: T0 + 10 }),
    mkEvent({ type: "run.started", sequence: 1, occurredAt: T0 + 20 }),
  ]);
  const r = reduceEvent(store, mkEvent({ type: "run.failed", sequence: 2, occurredAt: T0 + 5 }));
  assert.equal(r.applied, false);
  assert.equal(getRun(store, "r1").state, "running");
});

test("parent-child association by runId and parentRunId", () => {
  const { store } = applyEvents(createExecutionStore(), [
    mkEvent({ runId: "parent" }),
    mkEvent({ runId: "child1", agentId: "a2", parentRunId: "parent" }),
    mkEvent({ runId: "child2", agentId: "a3", parentRunId: "parent" }),
  ]);
  assert.deepEqual(
    childRuns(store, "parent").map((r) => r.runId),
    ["child1", "child2"]
  );
});

test("mission counts distinguish finished from succeeded", () => {
  const { store } = applyEvents(createExecutionStore(), [
    mkEvent({ runId: "r1", missionId: "m1" }),
    mkEvent({ runId: "r1", missionId: "m1", type: "run.completed", sequence: 1, occurredAt: T0 + 1 }),
    mkEvent({ runId: "r2", missionId: "m1", agentId: "a2" }),
    mkEvent({ runId: "r2", missionId: "m1", agentId: "a2", type: "run.failed", sequence: 1, occurredAt: T0 + 1, error: "boom" }),
    mkEvent({ runId: "r3", missionId: "m3", agentId: "a3" }),
    mkEvent({ runId: "r3", missionId: "m3", agentId: "a3", type: "run.waiting", sequence: 1, occurredAt: T0 + 1, waitingReason: "approval" }),
  ]);
  const c1 = missionCounts(store, "m1");
  assert.equal(c1.total, 2);
  assert.equal(c1.finished, 2);
  assert.equal(c1.succeeded, 1);
  assert.equal(c1.failed, 1);
  const c3 = missionCounts(store, "m3");
  assert.equal(c3.waiting, 1);
  assert.equal(c3.finished, 0);
});

test("memory query events produce retrieval records", () => {
  const { store } = applyEvents(createExecutionStore(), [
    mkEvent({ runId: "mq1", type: "memory.query.started", scope: "notes/demo" }),
    mkEvent({ runId: "mq1", type: "memory.query.completed", sequence: 1, occurredAt: T0 + 1, scope: "notes/demo" }),
  ]);
  assert.equal(store.retrievals.length, 1);
  assert.equal(store.retrievals[0].state, "succeeded");
  assert.equal(store.retrievals[0].scope, "notes/demo");
});

test("failed memory queries keep their error", () => {
  const { store } = applyEvents(createExecutionStore(), [
    mkEvent({ runId: "mq2", type: "memory.query.started", scope: "notes/x" }),
    mkEvent({ runId: "mq2", type: "memory.query.failed", sequence: 1, occurredAt: T0 + 1, scope: "notes/x", error: "vault locked" }),
  ]);
  assert.equal(store.retrievals[0].state, "failed");
  assert.equal(store.retrievals[0].error, "vault locked");
});

test("telemetry defaults to unavailable (absence is not fact)", () => {
  const store = createExecutionStore();
  assert.equal(telemetryLevel(store, "a1"), "unavailable");
  const { store: s2, errors } = setTelemetryLevel(store, "a1", "partial");
  assert.deepEqual(errors, []);
  assert.equal(telemetryLevel(s2, "a1"), "partial");
});

test("snapshot replaces state; later events still apply with dedupe", () => {
  const { store: s1 } = applyEvents(createExecutionStore("mock"), [mkEvent({ runId: "old" })]);
  const snapshot = {
    runs: { fresh: { runId: "fresh", state: "running", agentId: "a9" } },
    events: [{ eventId: "snap-1" }],
    missions: { m9: { missionId: "m9", runIds: ["fresh"] } },
  };
  const { store: s2 } = applySnapshot(s1, snapshot);
  assert.equal(getRun(s2, "old"), null);
  assert.equal(getRun(s2, "fresh").state, "running");
  const dup = reduceEvent(s2, { ...mkEvent({ eventId: "snap-1", runId: "fresh" }) });
  assert.equal(dup.applied, false);
  const { store: s3, applied } = reduceEvent(
    s2,
    mkEvent({ eventId: "late-1", runId: "fresh", sequence: 5, occurredAt: T0 + 100, type: "run.completed" })
  );
  assert.equal(applied, true);
  assert.equal(getRun(s3, "fresh").state, "succeeded");
});

test("store source is preserved through snapshots", () => {
  const store = createExecutionStore("mock");
  const { store: s2 } = applySnapshot(store, { runs: {}, events: [] });
  assert.equal(s2.source, "mock");
});
