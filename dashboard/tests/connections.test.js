import { test } from "node:test";
import assert from "node:assert/strict";
import { createRegistry } from "../src/model/registry.js";
import {
  canConnect,
  createConnections,
  connectionId,
  portId,
  listPorts,
  wouldCreateCycle,
  isDuplicate,
  compatibleTypes,
} from "../src/model/connections.js";

function demoRegistry() {
  return createRegistry([
    { id: "hermes", kind: "orchestrator", name: "Hermes" },
    { id: "dsh", kind: "agent", name: "DSH" },
    { id: "docker", kind: "tool", name: "Docker" },
    { id: "wp", kind: "tool", name: "WordPress" },
    { id: "mem", kind: "memory", name: "Shared Memory", provider: "obsidian" },
  ]);
}

test("orchestrator -> agent control connection is valid", () => {
  const reg = demoRegistry();
  assert.equal(canConnect(reg, [], { from: "hermes", to: "dsh", type: "control" }).ok, true);
});

test("tools may relay tool-access (docker -> wordpress)", () => {
  const reg = demoRegistry();
  const { list, errors } = createConnections(reg, [
    { from: "hermes", to: "docker", type: "tool-access" },
    { from: "docker", to: "wp", type: "tool-access" },
  ]);
  assert.deepEqual(errors, []);
  assert.equal(list.length, 2);
});

test("duplicate connections are rejected; a different type between the same pair is allowed", () => {
  const reg = demoRegistry();
  const { list } = createConnections(reg, [{ from: "hermes", to: "dsh", type: "control" }]);
  const dup = canConnect(reg, list, { from: "hermes", to: "dsh", type: "control" });
  assert.equal(dup.ok, false);
  assert.ok(dup.reason.includes("duplicate"));
  const alt = canConnect(reg, list, { from: "hermes", to: "dsh", type: "memory-read" });
  assert.equal(alt.ok, true);
});

test("self-connections are rejected", () => {
  const reg = demoRegistry();
  const res = canConnect(reg, [], { from: "hermes", to: "hermes", type: "control" });
  assert.equal(res.ok, false);
});

test("agents cannot output control", () => {
  const reg = demoRegistry();
  const res = canConnect(reg, [], { from: "dsh", to: "hermes", type: "control" });
  assert.equal(res.ok, false);
  assert.ok(res.reason.includes("control"));
});

test("memory nodes cannot initiate connections", () => {
  const reg = demoRegistry();
  const res = canConnect(reg, [], { from: "mem", to: "dsh", type: "memory-read" });
  assert.equal(res.ok, false);
});

test("agent -> memory read and orchestrator -> memory write are valid", () => {
  const reg = demoRegistry();
  assert.equal(canConnect(reg, [], { from: "dsh", to: "mem", type: "memory-read" }).ok, true);
  assert.equal(canConnect(reg, [], { from: "hermes", to: "mem", type: "memory-write" }).ok, true);
});

test("cycles are rejected for acyclic connection types", () => {
  const reg = createRegistry([
    { id: "t1", kind: "tool", name: "T1" },
    { id: "t2", kind: "tool", name: "T2" },
    { id: "t3", kind: "tool", name: "T3" },
  ]);
  const { list } = createConnections(reg, [
    { from: "t1", to: "t2", type: "tool-access" },
    { from: "t2", to: "t3", type: "tool-access" },
  ]);
  const res = canConnect(reg, list, { from: "t3", to: "t1", type: "tool-access" });
  assert.equal(res.ok, false);
  assert.ok(res.reason.includes("cycle"));
});

test("memory-read cycles are explicitly permitted (read-only policy)", () => {
  const reg = createRegistry([
    { id: "a1", kind: "agent", name: "A1" },
    { id: "a2", kind: "agent", name: "A2" },
  ]);
  const { list } = createConnections(reg, [{ from: "a1", to: "a2", type: "memory-read" }]);
  const res = canConnect(reg, list, { from: "a2", to: "a1", type: "memory-read" });
  assert.equal(res.ok, true);
});

test("wouldCreateCycle ignores disabled connections", () => {
  const conns = [
    { from: "t1", to: "t2", type: "tool-access", state: "disabled" },
    { from: "t2", to: "t3", type: "tool-access", state: "disabled" },
  ];
  assert.equal(wouldCreateCycle(conns, "t3", "t1", "tool-access"), false);
});

test("stable id helpers", () => {
  assert.equal(connectionId("a", "control", "b"), "conn-a-control-b");
  assert.equal(portId("a", "in", "control"), "a:in:control");
});

test("listPorts follows the compatibility table", () => {
  const reg = demoRegistry();
  const hermesPorts = listPorts(reg, "hermes").map((p) => p.id);
  assert.ok(hermesPorts.includes("hermes:out:control"));
  assert.ok(hermesPorts.includes("hermes:out:memory-read"));
  const memPorts = listPorts(reg, "mem").map((p) => p.id);
  assert.ok(memPorts.includes("mem:in:memory-read"));
  assert.ok(memPorts.includes("mem:in:memory-write"));
  assert.ok(!memPorts.some((p) => p.direction === "out"));
});

test("isDuplicate matches same from/to/type only", () => {
  const conns = [{ from: "a", to: "b", type: "control" }];
  assert.equal(isDuplicate(conns, { from: "a", to: "b", type: "control" }), true);
  assert.equal(isDuplicate(conns, { from: "a", to: "b", type: "tool-access" }), false);
});

test("compatibleTypes lists only valid types for a pair", () => {
  const reg = demoRegistry();
  // orchestrator out: control/tool-access/memory-read/memory-write
  // agent in: control/memory-read
  assert.deepEqual(compatibleTypes(reg, [], { from: "hermes", to: "dsh" }), [
    "control",
    "memory-read",
  ]);
});

test("compatibleTypes excludes duplicates, restore via excludeId", () => {
  const reg = demoRegistry();
  const conns = [
    { id: "conn-hermes-control-dsh", from: "hermes", to: "dsh", type: "control", state: "enabled" },
  ];
  // the existing control connection makes control a duplicate
  assert.deepEqual(compatibleTypes(reg, conns, { from: "hermes", to: "dsh" }), ["memory-read"]);
  // excluding the connection being edited restores control
  assert.deepEqual(
    compatibleTypes(reg, conns, { from: "hermes", to: "dsh" }, "conn-hermes-control-dsh"),
    ["control", "memory-read"]
  );
});

test("compatibleTypes returns empty for impossible pairs", () => {
  const reg = demoRegistry();
  // memory nodes cannot initiate
  assert.deepEqual(compatibleTypes(reg, [], { from: "mem", to: "dsh" }), []);
  // self-connections
  assert.deepEqual(compatibleTypes(reg, [], { from: "hermes", to: "hermes" }), []);
  // agents cannot output control, and the orchestrator accepts no inputs
  assert.deepEqual(compatibleTypes(reg, [], { from: "dsh", to: "hermes" }), []);
});
