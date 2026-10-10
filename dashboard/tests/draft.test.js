import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createDraft,
  addChange,
  removeChange,
  discardDraft,
  summarizeDraft,
  applyResultsToDraft,
  createHistory,
  commit,
  undo,
  redo,
} from "../src/model/draft.js";

test("addChange validates op and payload", () => {
  const d = createDraft();
  const { draft, added, errors } = addChange(d, {
    op: "addEntity",
    entity: { id: "x", kind: "agent", name: "X" },
  });
  assert.equal(added, true);
  assert.equal(errors.length, 0);
  assert.equal(draft.changes.length, 1);
  assert.equal(draft.changes[0].status, "pending");
  assert.match(draft.changes[0].opId, /^op-/);
  assert.equal(d.changes.length, 0); // original untouched (pure)
});

test("addChange rejects unknown ops and bad payloads", () => {
  const d = createDraft();
  assert.equal(addChange(d, { op: "launchMissiles" }).added, false);
  assert.equal(addChange(d, { op: "removeEntity" }).added, false); // missing entityId
  assert.equal(
    addChange(d, { op: "setConnectionState", connectionId: "c1", state: "maybe" }).added,
    false
  );
  assert.equal(addChange(d, null).added, false);
});

// ---- Skill 07: navigation / page draft ops ----

test("addChange accepts the navigation and page ops", () => {
  const d = createDraft();
  const nav = addChange(d, {
    op: "addNavItem",
    item: { id: "audit", route: "/audit", label: { en: "Audit", fa: "ممیزی" } },
  });
  assert.equal(nav.added, true);
  const mv = addChange(nav.draft, { op: "moveNav", navId: "audit", delta: -1 });
  assert.equal(mv.added, true);
  const vis = addChange(mv.draft, { op: "setNavVisibility", navId: "audit", visible: false });
  assert.equal(vis.added, true);
  const pg = addChange(vis.draft, {
    op: "addPage",
    page: { id: "p-audit", route: "/audit", renderer: "timeline", title: { en: "Audit", fa: "ممیزی" } },
  });
  assert.equal(pg.added, true);
  assert.equal(pg.draft.changes.length, 4);
  assert.ok(pg.draft.changes.every((c) => c.status === "pending"));
});

test("addChange rejects malformed navigation and page payloads", () => {
  const d = createDraft();
  assert.equal(addChange(d, { op: "addNavItem" }).added, false);
  assert.equal(addChange(d, { op: "addNavItem", item: {} }).added, false);
  assert.equal(addChange(d, { op: "moveNav", navId: "a" }).added, false); // missing delta
  assert.equal(addChange(d, { op: "moveNav", navId: "a", delta: 2 }).added, false);
  assert.equal(addChange(d, { op: "setNavVisibility", navId: "a" }).added, false);
  assert.equal(
    addChange(d, { op: "setNavVisibility", navId: "a", visible: "yes" }).added,
    false
  );
  assert.equal(addChange(d, { op: "addPage", page: {} }).added, false);
});

test("summarizeDraft reports navigation and page changes", () => {
  let d = createDraft();
  d = addChange(d, {
    op: "addNavItem",
    item: { id: "audit", route: "/audit", label: { en: "Audit", fa: "ممیزی" } },
  }).draft;
  d = addChange(d, { op: "moveNav", navId: "audit", delta: 1 }).draft;
  d = addChange(d, { op: "setNavVisibility", navId: "tools", visible: false }).draft;
  d = addChange(d, {
    op: "addPage",
    page: { id: "p-audit", route: "/audit", renderer: "timeline", title: { en: "A", fa: "آ" } },
  }).draft;
  const s = summarizeDraft(d);
  assert.equal(s.addedNavItems.length, 1);
  assert.equal(s.addedNavItems[0].id, "audit");
  assert.deepEqual(s.movedNavItems, [{ navId: "audit", delta: 1 }]);
  assert.deepEqual(s.navVisibility, [{ navId: "tools", visible: false }]);
  assert.equal(s.addedPages.length, 1);
  assert.equal(s.addedPages[0].route, "/audit");
  assert.equal(s.total, 4);
  // A rejected nav op stays in the draft WITH its reason.
  const rejected = applyResultsToDraft(d, [
    { opId: d.changes[0].opId, status: "rejected", reason: "duplicate route: /audit" },
  ]).draft;
  const s2 = summarizeDraft(rejected);
  assert.equal(s2.addedNavItems.length, 0); // no longer pending
  assert.equal(s2.rejectedChanges.length, 1);
  assert.ok(s2.rejectedChanges[0].reason.includes("duplicate"));
  assert.equal(s2.total, 3);
});

test("removeChange and discardDraft", () => {
  let d = createDraft();
  d = addChange(d, { op: "removeEntity", entityId: "x" }).draft;
  const { draft: d2 } = removeChange(d, d.changes[0].opId);
  assert.equal(d2.changes.length, 0);
  const { draft: d3 } = addChange(d, { op: "removeEntity", entityId: "y" });
  assert.equal(discardDraft(d3).changes.length, 0);
});

test("summarizeDraft groups pending changes by kind", () => {
  let d = createDraft();
  d = addChange(d, { op: "addEntity", entity: { id: "a", kind: "agent", name: "A" } }).draft;
  d = addChange(d, {
    op: "addConnection",
    connection: { id: "c1", from: "h", to: "a", type: "control" },
  }).draft;
  d = addChange(d, { op: "changePermission", agentId: "a", scope: "memory.read", allowed: true }).draft;
  const s = summarizeDraft(d, [{ type: "move", id: "a" }]);
  assert.equal(s.addedEntities.length, 1);
  assert.equal(s.addedConnections.length, 1);
  assert.equal(s.changedPermissions.length, 1);
  assert.equal(s.removedEntities.length, 0);
  assert.equal(s.layoutOnly.length, 1);
  assert.equal(s.total, 3);
});

test("applyResultsToDraft marks per-op results and keeps rejected items", () => {
  let d = createDraft();
  d = addChange(d, { op: "addEntity", entity: { id: "a", kind: "agent", name: "A" } }).draft;
  const opId = d.changes[0].opId;
  d = applyResultsToDraft(d, [{ opId, status: "rejected", reason: "duplicate id" }]).draft;
  assert.equal(d.changes[0].status, "rejected");
  assert.equal(d.changes[0].reason, "duplicate id");
  assert.equal(summarizeDraft(d).total, 0); // rejected items leave the pending summary
});

test("undo/redo round-trip", () => {
  let h = createHistory();
  const s1 = { draft: createDraft(), view: { zoom: 1 } };
  const current = { draft: createDraft(), view: { zoom: 3 } };
  h = commit(h, s1);
  const u = undo(h, current);
  assert.deepEqual(u.snapshot, s1);
  const r = redo(u.history, current);
  assert.deepEqual(r.snapshot, current);
});

test("history is bounded", () => {
  let h = createHistory(3);
  for (let i = 0; i < 10; i++) h = commit(h, { i });
  assert.equal(h.past.length, 3);
  assert.deepEqual(h.past[2], { i: 9 });
});

test("the redo branch clears on a new commit", () => {
  let h = createHistory();
  h = commit(h, { i: 1 });
  const u = undo(h, { i: 2 });
  const h2 = commit(u.history, { i: 3 });
  assert.deepEqual(h2.future, []);
});

test("undo/redo with empty history returns a null snapshot", () => {
  const h = createHistory();
  assert.equal(undo(h, {}).snapshot, null);
  assert.equal(redo(h, {}).snapshot, null);
});
