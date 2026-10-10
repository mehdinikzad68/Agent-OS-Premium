// Pure geometry tests for the scene layout module.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bez,
  bezWithMidpoint,
  strandAt,
  strandMidpoint,
  clampPosition,
  nearestStrand,
  computeLayout,
} from "../src/scene/layout.js";

const AGENTS = [
  { id: "hermes", name: "Hermes" },
  { id: "a", name: "A" },
  { id: "b", name: "B" },
];
const LINKS = [
  { id: "c1", from: "hermes", to: "a" },
  { id: "c2", from: "hermes", to: "b" },
];

test("bez samples endpoints exactly", () => {
  const pts = bez({ x: 0, y: 0 }, { x: 0, y: 10 }, { x: 10, y: 10 }, { x: 10, y: 0 }, 10);
  assert.deepEqual([pts[0], pts[1]], [0, 0]);
  assert.deepEqual([pts[20], pts[21]], [10, 0]);
});

test("bezWithMidpoint passes through the requested midpoint", () => {
  const pts = bezWithMidpoint(
    { x: 0, y: 0 },
    { x: 0, y: 100 },
    { x: 100, y: 100 },
    { x: 100, y: 0 },
    { x: 50, y: 50 },
    20
  );
  const half = strandAt(pts, 0.5);
  assert.ok(Math.abs(half[0] - 50) < 1e-6);
  assert.ok(Math.abs(half[1] - 50) < 1e-6);
});

test("bezWithMidpoint without a midpoint equals bez", () => {
  const p0 = { x: 0, y: 0 };
  const p1 = { x: 0, y: 30 };
  const p2 = { x: 30, y: 30 };
  const p3 = { x: 30, y: 0 };
  const a = bez(p0, p1, p2, p3, 12);
  const b = bezWithMidpoint(p0, p1, p2, p3, null, 12);
  assert.deepEqual([...a], [...b]);
});

test("strandMidpoint is the middle strand at t=0.5", () => {
  const strands = [
    bez({ x: 0, y: 0 }, { x: 0, y: 10 }, { x: 10, y: 10 }, { x: 10, y: 0 }),
    bez({ x: 5, y: 0 }, { x: 5, y: 10 }, { x: 15, y: 10 }, { x: 15, y: 0 }),
    bez({ x: 10, y: 0 }, { x: 10, y: 10 }, { x: 20, y: 10 }, { x: 20, y: 0 }),
  ];
  const mid = strandMidpoint(strands);
  // middle strand (index 1) midpoint: x = (5 + 3*5 + 3*15 + 15)/8 = 10
  assert.ok(Math.abs(mid[0] - 10) < 1e-6);
});

test("clampPosition keeps points inside the canvas", () => {
  assert.deepEqual(clampPosition({ x: -10, y: 999 }, 800, 520), { x: 44, y: 476 });
  assert.deepEqual(clampPosition({ x: 100, y: 100 }, 800, 520), { x: 100, y: 100 });
});

test("nearestStrand finds hits within the threshold and ignores far points", () => {
  const strands = [bez({ x: 0, y: 260 }, { x: 200, y: 260 }, { x: 400, y: 260 }, { x: 800, y: 260 })];
  const fibers = [{ id: "f", from: "hermes", to: "a", strands }];
  const hit = nearestStrand(fibers, { x: 400, y: 265 }, 14);
  assert.equal(hit.fiber.id, "f");
  assert.equal(nearestStrand(fibers, { x: 400, y: 400 }, 14), null);
});

test("computeLayout places the coordinator at the center", () => {
  const { C, nodes } = computeLayout(AGENTS, LINKS, 800, 520);
  assert.deepEqual(nodes.hermes, { x: C.x, y: 520 * 0.47, side: 0 });
  assert.equal(C.x, 400);
});

test("computeLayout honors manual view positions and clamps them", () => {
  const { nodes } = computeLayout(AGENTS, LINKS, 800, 520, { a: { x: 10, y: 10 } });
  assert.deepEqual({ x: nodes.a.x, y: nodes.a.y }, { x: 44, y: 44 });
});

test("computeLayout builds fibers for every link", () => {
  const { fibers } = computeLayout(AGENTS, LINKS, 800, 520);
  assert.deepEqual(fibers.map((f) => f.id), ["c1", "c2"]);
  assert.ok(fibers.every((f) => f.strands.length > 0));
});

test("computeLayout applies fiber curvature midpoints", () => {
  const base = computeLayout(AGENTS, LINKS, 800, 520);
  const curved = computeLayout(AGENTS, LINKS, 800, 520, {}, { c1: { midpoint: { x: 400, y: 100 } } });
  const midCurved = strandMidpoint(curved.fibers[0].strands);
  assert.ok(Math.abs(midCurved[0] - 400) < 1e-6);
  assert.ok(Math.abs(midCurved[1] - 100) < 1e-6);
  // the fiber without curvature metadata is untouched
  assert.deepEqual(
    strandMidpoint(base.fibers[1].strands),
    strandMidpoint(computeLayout(AGENTS, LINKS, 800, 520).fibers[1].strands)
  );
});
