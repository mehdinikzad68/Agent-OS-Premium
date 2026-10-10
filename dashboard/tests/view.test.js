import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createDefaultView,
  validateViewState,
  sanitizeViewState,
  setPosition,
  setLocked,
  setHidden,
  setFiberMidpoint,
  setGroup,
  saveNamedView,
  resetLayout,
  worldToScreen,
  screenToWorld,
} from "../src/model/view.js";

test("default view has the expected shape", () => {
  const v = createDefaultView();
  assert.equal(v.schemaVersion, 1);
  assert.deepEqual(v.positions, {});
  assert.deepEqual(v.viewport, { zoom: 1, panX: 0, panY: 0 });
});

test("validateViewState accepts a valid view", () => {
  const v = setPosition(setLocked(createDefaultView(), "a", true), "a", 10, 20);
  assert.equal(validateViewState(v).ok, true);
});

test("validateViewState reports malformed positions", () => {
  const res = validateViewState({ ...createDefaultView(), positions: { a: { x: "x", y: 1 } } });
  assert.equal(res.ok, false);
  assert.ok(res.errors.some((e) => e.includes('"a"')));
});

test("sanitizeViewState keeps valid sections and drops malformed ones", () => {
  const { view, errors } = sanitizeViewState({
    schemaVersion: 1,
    positions: { good: { x: 1, y: 2 }, bad: { x: "NaN" } },
    viewport: { zoom: 2, panX: 10, panY: 20 },
    hidden: "nope",
  });
  assert.deepEqual(view.positions, { good: { x: 1, y: 2, locked: false } });
  assert.deepEqual(view.viewport, { zoom: 2, panX: 10, panY: 20 });
  assert.ok(errors.length >= 2);
});

test("updaters are pure", () => {
  const v = createDefaultView();
  const v2 = setPosition(v, "a", 5, 6);
  assert.deepEqual(v.positions, {});
  assert.deepEqual(v2.positions, { a: { x: 5, y: 6 } });
});

test("setLocked and setHidden", () => {
  let v = setLocked(createDefaultView(), "a", true);
  assert.equal(v.positions.a.locked, true);
  v = setHidden(v, "a", true);
  assert.deepEqual(v.hidden, ["a"]);
  v = setHidden(v, "a", false);
  assert.deepEqual(v.hidden, []);
});

test("setFiberMidpoint and setGroup", () => {
  let v = setFiberMidpoint(createDefaultView(), "conn-1", { x: 3, y: 4 });
  assert.deepEqual(v.fiberGeometry["conn-1"], { midpoint: { x: 3, y: 4 } });
  v = setGroup(v, "g1", { label: "G", memberIds: ["a"], collapsed: true });
  assert.equal(v.groups.g1.collapsed, true);
  assert.deepEqual(v.groups.g1.memberIds, ["a"]);
});

test("saveNamedView stores a snapshot", () => {
  let v = setPosition(createDefaultView(), "a", 1, 2);
  v = saveNamedView(v, "view-1", "My view");
  assert.equal(v.savedViews.length, 1);
  assert.equal(v.savedViews[0].name, "My view");
  assert.deepEqual(v.savedViews[0].view.positions, { a: { x: 1, y: 2 } });
});

test("resetLayout clears layout only, not entities or saved sections", () => {
  let v = setPosition(createDefaultView(), "a", 1, 2);
  v = setHidden(v, "a", true);
  v = setGroup(v, "g", { label: "G", memberIds: ["a"] });
  v = setFiberMidpoint(v, "c1", { x: 1, y: 1 });
  v = { ...v, viewport: { zoom: 3, panX: 30, panY: 30 } };
  const r = resetLayout(v);
  assert.deepEqual(r.positions, {});
  assert.deepEqual(r.fiberGeometry, {});
  assert.deepEqual(r.viewport, { zoom: 1, panX: 0, panY: 0 });
  assert.deepEqual(r.hidden, ["a"]);
  assert.ok(r.groups.g);
});

test("world/screen round-trip with zoom and pan", () => {
  const v = { ...createDefaultView(), viewport: { zoom: 2, panX: 10, panY: 20 } };
  const p = { x: 100, y: -50 };
  assert.deepEqual(screenToWorld(v, worldToScreen(v, p)), p);
});
