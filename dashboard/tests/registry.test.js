import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createRegistry,
  addEntity,
  removeEntity,
  getCoordinator,
  validateEntity,
  entitiesOfKind,
} from "../src/model/registry.js";

const base = (over = {}) => ({ id: "a1", kind: "agent", name: "Agent One", ...over });

test("registry accepts valid entities", () => {
  const { byId, errors } = createRegistry([base(), base({ id: "a2", name: "Agent Two" })]);
  assert.equal(errors.length, 0);
  assert.equal(Object.keys(byId).length, 2);
});

test("rejects duplicate ids", () => {
  const { errors } = createRegistry([base(), base()]);
  assert.ok(errors.some((e) => e.includes("duplicate id")));
});

test("rejects unknown kind", () => {
  const { errors } = createRegistry([base({ kind: "wizard" })]);
  assert.ok(errors.some((e) => e.includes("kind")));
});

test("accepts exactly one orchestrator", () => {
  const { errors } = createRegistry([
    { id: "core", kind: "orchestrator", name: "Core" },
    { id: "core2", kind: "orchestrator", name: "Core Two" },
  ]);
  assert.ok(errors.some((e) => e.includes("exactly one orchestrator")));
});

test("memory entities require a provider", () => {
  const { errors } = createRegistry([{ id: "mem", kind: "memory", name: "Shared Memory" }]);
  assert.ok(errors.some((e) => e.includes("provider")));
});

test("parent must reference a registered id", () => {
  const { errors } = createRegistry([base({ id: "child", parent: "ghost" })]);
  assert.ok(errors.some((e) => e.includes("not registered")));
});

test("addEntity is pure and rejects invalid input", () => {
  const reg = createRegistry([base()]);
  const { registry, added, errors } = addEntity(reg, base({ id: "a2", name: "Two" }));
  assert.equal(added, true);
  assert.equal(errors.length, 0);
  assert.equal(Object.keys(reg.byId).length, 1); // original untouched
  assert.equal(Object.keys(registry.byId).length, 2);
  const bad = addEntity(reg, base({ id: "a3", name: "" }));
  assert.equal(bad.added, false);
});

test("orchestrator cannot be unregistered", () => {
  const reg = createRegistry([{ id: "core", kind: "orchestrator", name: "Core" }]);
  const { removed, errors } = removeEntity(reg, "core");
  assert.equal(removed, false);
  assert.ok(errors.length > 0);
});

test("coordinator is found by role (kind), not by id", () => {
  const registry = createRegistry([
    { id: "nexus", kind: "orchestrator", name: "Nexus" },
    base(),
  ]);
  assert.equal(getCoordinator(registry).id, "nexus");
});

test("entitiesOfKind filters correctly", () => {
  const registry = createRegistry([
    { id: "core", kind: "orchestrator", name: "Core" },
    base(),
    { id: "t1", kind: "tool", name: "Tool" },
  ]);
  assert.deepEqual(entitiesOfKind(registry, "tool").map((e) => e.id), ["t1"]);
});

test("validateEntity requires a non-empty name", () => {
  assert.equal(validateEntity(base({ name: "" })).ok, false);
});
