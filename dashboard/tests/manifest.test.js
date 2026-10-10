import { test } from "node:test";
import assert from "node:assert/strict";
import {
  validateManifest,
  validatePages,
  resolveNavItems,
  sortNavItems,
  resolveRenderer,
  resolvePage,
  visibleNavItems,
  pageFromTemplate,
  PAGE_TEMPLATES,
} from "../src/model/manifest.js";

function item(over = {}) {
  return {
    id: "home",
    label: { en: "Home", fa: "خانه" },
    icon: "home",
    route: "/home",
    renderer: "command-canvas",
    order: 10,
    visible: true,
    capabilities: [],
    permissions: [],
    ...over,
  };
}

test("a valid manifest passes", () => {
  const res = validateManifest({ schemaVersion: 1, items: [item()] });
  assert.equal(res.ok, true);
});

test("unknown renderers are rejected with a readable error", () => {
  const res = validateManifest({ schemaVersion: 1, items: [item({ renderer: "magic-panel" })] });
  assert.equal(res.ok, false);
  assert.ok(res.errors.some((e) => e.includes("magic-panel") && e.includes("renderer")));
});

test("unknown icons are rejected", () => {
  const res = validateManifest({ schemaVersion: 1, items: [item({ icon: "unicorn" })] });
  assert.equal(res.ok, false);
  assert.ok(res.errors.some((e) => e.includes("unicorn")));
});

test("duplicate ids and routes are rejected", () => {
  const res = validateManifest({
    schemaVersion: 1,
    items: [item(), item({ label: { en: "Home 2", fa: "خانه ۲" } })],
  });
  assert.equal(res.ok, false);
  assert.ok(res.errors.some((e) => e.includes("duplicate")));
});

test("unsupported schemaVersion is rejected", () => {
  const res = validateManifest({ schemaVersion: 99, items: [item()] });
  assert.equal(res.ok, false);
});

test("resolveNavItems gates entries by capabilities and permissions", () => {
  const manifest = {
    schemaVersion: 1,
    items: [
      item({ id: "open", capabilities: ["memory.read"] }),
      item({ id: "admin", permissions: ["admin.write"] }),
      item({ id: "plain" }),
    ],
  };
  const byId = Object.fromEntries(
    resolveNavItems(manifest, { capabilities: ["memory.read"], permissions: [] }).map((r) => [r.id, r])
  );
  assert.equal(byId.open.available, true);
  assert.equal(byId.admin.available, false);
  assert.ok(byId.admin.unavailableReason.includes("permissions"));
  assert.equal(byId.plain.available, true);
});

test("sortNavItems orders by the declared order", () => {
  const manifest = {
    schemaVersion: 1,
    items: [item({ id: "b", order: 20, route: "/b" }), item({ id: "a", order: 10, route: "/a" })],
  };
  assert.deepEqual(
    sortNavItems(manifest).map((i) => i.id),
    ["a", "b"]
  );
});

test("validatePages checks renderers and unique routes", () => {
  const res = validatePages([
    { id: "p1", route: "/p1", renderer: "timeline", title: { en: "T", fa: "ت" } },
    { id: "p2", route: "/p1", renderer: "timeline", title: { en: "T", fa: "ت" } },
    { id: "p3", route: "/p3", renderer: "nope", title: { en: "T", fa: "ت" } },
  ]);
  assert.equal(res.ok, false);
  assert.ok(res.errors.some((e) => e.includes("duplicate route")));
  assert.ok(res.errors.some((e) => e.includes("nope")));
});

test("resolveRenderer returns safe errors, never throws", () => {
  const registry = { "resource-table": {} };
  const bad = resolveRenderer("nope", registry);
  assert.equal(bad.ok, false);
  assert.ok(bad.error.includes("unknown page renderer"));
  const missing = resolveRenderer("timeline", registry);
  assert.equal(missing.ok, false);
  assert.ok(missing.error.includes("not registered"));
  // registered → the component itself
  const ok = resolveRenderer("resource-table", registry);
  assert.equal(ok.ok, true);
  assert.equal(ok.component, registry["resource-table"]);
});

// ---- Skill 07: resolvePage / visibility / templates ----

function navItem(over = {}) {
  return item(over);
}

function pageDef(over = {}) {
  return {
    id: "p-agents",
    route: "/agents",
    renderer: "resource-table",
    title: { en: "Agents", fa: "عامل‌ها" },
    props: { source: "agents" },
    ...over,
  };
}

test("resolvePage prefers the page definition and attaches the nav item", () => {
  const manifest = { schemaVersion: 1, items: [navItem({ route: "/agents", renderer: "resource-table" })] };
  const pages = [pageDef()];
  const res = resolvePage("/agents", manifest, pages);
  assert.equal(res.ok, true);
  assert.equal(res.page.renderer, "resource-table");
  assert.equal(res.page.title.en, "Agents");
  assert.deepEqual(res.page.props, { source: "agents" });
  assert.equal(res.item.id, "home");
});

test("resolvePage falls back to the nav item when no page exists", () => {
  const manifest = { schemaVersion: 1, items: [navItem({ route: "/solo", renderer: "timeline", label: { en: "Solo", fa: "تکی" } })] };
  const res = resolvePage("/solo", manifest, []);
  assert.equal(res.ok, true);
  assert.equal(res.page.renderer, "timeline");
  assert.equal(res.page.title.fa, "تکی");
  assert.deepEqual(res.page.props, {});
});

test("resolvePage renders a page even without a nav item", () => {
  const res = resolvePage("/only-page", { schemaVersion: 1, items: [] }, [pageDef({ route: "/only-page" })]);
  assert.equal(res.ok, true);
  assert.equal(res.page.renderer, "resource-table");
});

test("resolvePage reports an unknown route as a readable error", () => {
  const res = resolvePage("/nothing", { schemaVersion: 1, items: [] }, []);
  assert.equal(res.ok, false);
  assert.ok(res.error.includes("/nothing"));
});

test("resolvePage is defensive about a renderer-less item", () => {
  const manifest = {
    schemaVersion: 1,
    items: [{ id: "x", route: "/x", label: { en: "X", fa: "ایکس" }, order: 10 }],
  };
  const res = resolvePage("/x", manifest, []);
  assert.equal(res.ok, true);
  assert.equal(res.page.renderer, null);
  // …and the renderer resolution then fails SAFE, not a crash.
  const r = resolveRenderer(res.page.renderer, {});
  assert.equal(r.ok, false);
  assert.ok(r.error.includes("unknown page renderer"));
});

test("visibleNavItems drops hidden entries without deleting their data", () => {
  const manifest = {
    schemaVersion: 1,
    items: [
      item({ id: "a", route: "/a", order: 10, visible: true }),
      item({ id: "b", route: "/b", order: 20, visible: false, label: { en: "B", fa: "بی" } }),
    ],
  };
  const resolved = resolveNavItems(manifest);
  const visible = visibleNavItems(resolved);
  assert.deepEqual(visible.map((i) => i.id), ["a"]);
  // The hidden entry's data is untouched in the manifest.
  assert.equal(manifest.items.length, 2);
  assert.equal(manifest.items[1].visible, false);
  assert.equal(manifest.items[1].route, "/b");
});

test("resolveNavItems exposes structured missing capability/permission lists", () => {
  const manifest = {
    schemaVersion: 1,
    items: [item({ capabilities: ["live-telemetry"], permissions: ["admin.write"] })],
  };
  const [r] = resolveNavItems(manifest, { capabilities: [], permissions: [] });
  assert.equal(r.available, false);
  assert.deepEqual(r.missingCapabilities, ["live-telemetry"]);
  assert.deepEqual(r.missingPermissions, ["admin.write"]);
  assert.ok(r.unavailableReason.includes("live-telemetry"));
});

test("PAGE_TEMPLATES are pure data with known renderers and unique routes", () => {
  const routes = new Set();
  for (const tpl of PAGE_TEMPLATES) {
    assert.ok(tpl.route.startsWith("/"), tpl.route);
    assert.equal(routes.has(tpl.route), false, `unique template route: ${tpl.route}`);
    routes.add(tpl.route);
    assert.ok(["resource-table", "resource-detail", "schema-form", "timeline"].includes(tpl.renderer));
    assert.ok(tpl.label.en && tpl.label.fa, `localized label: ${tpl.id}`);
    // No executable code in a template — data fields only.
    const keys = Object.keys(tpl);
    assert.ok(!keys.some((k) => typeof tpl[k] === "function"));
  }
});

test("pageFromTemplate produces a valid page + nav entry pair", () => {
  const tpl = PAGE_TEMPLATES[0];
  const { page, item: nav } = pageFromTemplate(tpl, { order: 120 });
  assert.equal(page.route, tpl.route);
  assert.equal(nav.route, tpl.route);
  assert.equal(nav.order, 120);
  assert.equal(validatePages([page]).ok, true);
  const manifest = {
    schemaVersion: 1,
    items: [item({ id: "home", order: 10 }), nav],
  };
  assert.equal(validateManifest(manifest).ok, true);
  // props are deep-copied — the template is never mutated.
  page.props.source = "mutated";
  assert.equal(tpl.props.source, "connections");
});
