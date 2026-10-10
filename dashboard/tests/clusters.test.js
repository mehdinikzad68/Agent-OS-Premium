// Skill 06: clusters, timeline and freshness helpers.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createExecutionStore,
  applyEvents,
  subagentFreshness,
  setSubagentFreshness,
  buildClusters,
  runSubtree,
  runInterval,
  intervalsOverlap,
  waitingSegments,
  elapsedMs,
  runsInOrder,
  depthOfRun,
  missionList,
  getRun,
} from "../src/model/runtime.js";

const T0 = 1_700_000_000_000;
let n = 0;
function ev(over = {}) {
  n += 1;
  return {
    eventId: `e${n}`,
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

test("subagent freshness defaults to unavailable and can be set", () => {
  const store = createExecutionStore();
  assert.equal(subagentFreshness(store, "a1"), "unavailable");
  const { store: s2, errors } = setSubagentFreshness(store, "a1", "stale");
  assert.deepEqual(errors, []);
  assert.equal(subagentFreshness(s2, "a1"), "stale");
  const { store: s3, errors: e3 } = setSubagentFreshness(s2, "a1", "bogus");
  assert.ok(e3.length > 0);
  assert.equal(subagentFreshness(s3, "a1"), "stale"); // unchanged
});

test("buildClusters counts children and excludes unavailable telemetry", () => {
  const { store } = applyEvents(createExecutionStore(), [
    ev({ runId: "parent", agentId: "a1" }),
    ev({ runId: "c1", agentId: "a2", parentRunId: "parent", type: "run.completed", sequence: 1, occurredAt: T0 + 1 }),
    ev({ runId: "c2", agentId: "a3", parentRunId: "parent", type: "run.waiting", sequence: 1, occurredAt: T0 + 1, waitingReason: "approval" }),
    ev({ runId: "c3", agentId: "a4", parentRunId: "parent", type: "run.failed", sequence: 1, occurredAt: T0 + 1, error: "boom" }),
  ]);
  const s1 = setSubagentFreshness(store, "a1", "fresh").store;
  const clusters = buildClusters(s1);
  assert.equal(clusters.length, 1);
  assert.equal(clusters[0].parentRunId, "parent");
  assert.equal(clusters[0].counts.total, 3);
  assert.equal(clusters[0].counts.active, 1); // only the waiting child
  assert.equal(clusters[0].counts.waiting, 1);
  assert.equal(clusters[0].counts.failed, 1);
  assert.equal(clusters[0].counts.succeeded, 1);
  // A provider without subagent telemetry is excluded —
  // the UI must never show an established zero.
  const s2 = setSubagentFreshness(s1, "a1", "unavailable").store;
  assert.equal(buildClusters(s2).length, 0);
});

test("runSubtree flattens nested children with depth", () => {
  const { store } = applyEvents(createExecutionStore(), [
    ev({ runId: "p" }),
    ev({ runId: "c1", parentRunId: "p", sequence: 1, occurredAt: T0 + 1 }),
    ev({ runId: "c2", parentRunId: "p", sequence: 2, occurredAt: T0 + 2 }),
    ev({ runId: "n1", parentRunId: "c1", sequence: 3, occurredAt: T0 + 3 }),
  ]);
  const rows = runSubtree(store, "p");
  assert.deepEqual(
    rows.map((r) => [r.run.runId, r.depth]),
    [
      ["p", 0],
      ["c1", 1],
      ["n1", 2],
      ["c2", 1],
    ]
  );
  assert.equal(depthOfRun(store, "n1"), 2);
  assert.equal(depthOfRun(store, "p"), 0);
});

test("intervalsOverlap detects concurrent runs", () => {
  const { store } = applyEvents(createExecutionStore(), [
    ev({ runId: "r1", type: "run.started", sequence: 1, occurredAt: T0 + 10 }),
    ev({ runId: "r1", type: "run.completed", sequence: 2, occurredAt: T0 + 30 }),
    ev({ runId: "r2", type: "run.started", sequence: 1, occurredAt: T0 + 20 }),
    ev({ runId: "r2", type: "run.completed", sequence: 2, occurredAt: T0 + 40 }),
    ev({ runId: "r3", type: "run.started", sequence: 1, occurredAt: T0 + 50 }),
    ev({ runId: "r3", type: "run.completed", sequence: 2, occurredAt: T0 + 60 }),
  ]);
  const r1 = runInterval(getRun(store, "r1"));
  const r2 = runInterval(getRun(store, "r2"));
  const r3 = runInterval(getRun(store, "r3"));
  assert.equal(intervalsOverlap(r1, r2), true); // 10-30 vs 20-40
  assert.equal(intervalsOverlap(r2, r3), false); // 20-40 vs 50-60
  assert.equal(intervalsOverlap(r1, r3), false);
});

test("waitingSegments derives waiting intervals from state history", () => {
  const { store } = applyEvents(createExecutionStore(), [
    ev({ runId: "w1", type: "run.started", sequence: 1, occurredAt: T0 + 1 }),
    ev({ runId: "w1", type: "run.waiting", sequence: 2, occurredAt: T0 + 5, waitingReason: "tool" }),
    ev({ runId: "w1", type: "run.started", sequence: 3, occurredAt: T0 + 9 }),
    ev({ runId: "w1", type: "run.completed", sequence: 4, occurredAt: T0 + 12 }),
  ]);
  const segs = waitingSegments(getRun(store, "w1"));
  assert.equal(segs.length, 1);
  assert.equal(segs[0].from, T0 + 5);
  assert.equal(segs[0].to, T0 + 9);
});

test("elapsedMs measures started -> ended", () => {
  const { store } = applyEvents(createExecutionStore(), [
    ev({ runId: "x1", type: "run.started", sequence: 1, occurredAt: T0 + 100 }),
    ev({ runId: "x1", type: "run.completed", sequence: 2, occurredAt: T0 + 350 }),
  ]);
  assert.equal(elapsedMs(getRun(store, "x1")), 250);
  const fresh = createExecutionStore();
  assert.equal(elapsedMs(getRun(fresh, "never")), null);
});

test("runsInOrder sorts by start time", () => {
  const { store } = applyEvents(createExecutionStore(), [
    ev({ runId: "late", type: "run.started", sequence: 1, occurredAt: T0 + 50 }),
    ev({ runId: "early", type: "run.started", sequence: 1, occurredAt: T0 + 10 }),
    ev({ runId: "mid", type: "run.started", sequence: 1, occurredAt: T0 + 30 }),
  ]);
  assert.deepEqual(
    runsInOrder(store).map((r) => r.runId),
    ["early", "mid", "late"]
  );
});

test("assignedTask is stored on the run record", () => {
  const { store } = applyEvents(createExecutionStore(), [
    ev({ runId: "t1", assignedTask: "Do the thing" }),
  ]);
  assert.equal(getRun(store, "t1").assignedTask, "Do the thing");
});

test("missionList returns sorted mission ids", () => {
  const { store } = applyEvents(createExecutionStore(), [
    ev({ runId: "m1", missionId: "zeta" }),
    ev({ runId: "m2", missionId: "alpha", sequence: 1, occurredAt: T0 + 1 }),
  ]);
  assert.deepEqual(missionList(store), ["alpha", "zeta"]);
});
