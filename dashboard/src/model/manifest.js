// Declarative navigation + page manifest model (pure, validated).
//
// Manifests contain DATA ONLY — never executable code. Icon and
// renderer references are string identifiers resolved against
// allowlists; unknown names produce safe, readable errors instead of
// crashes. Hiding a UI action is NOT server-side authorization.

export const MANIFEST_SCHEMA_VERSION = 1;

/** Icon identifiers allowed in manifests. The UI maps these to
 * components (see the Sidebar renderer registry). */
export const ICON_ALLOWLIST = [
  "home",
  "rocket",
  "network",
  "bot",
  "cpu",
  "wrench",
  "history",
  "file-text",
  "settings",
  "help",
  "shield",
  "memory",
  "activity",
  "layers",
  "globe",
  "database",
  "code",
  "box",
  "search",
  "plus",
];

/** Initial standard page renderers. */
export const RENDERER_ALLOWLIST = [
  "resource-table",
  "resource-detail",
  "schema-form",
  "timeline",
  "command-canvas",
];

const isNonEmptyString = (v) => typeof v === "string" && v.length > 0;
const isLocalized = (v) =>
  v && typeof v === "object" && isNonEmptyString(v.en) && isNonEmptyString(v.fa);

/**
 * Validate one navigation item.
 * @returns {{ok:boolean, errors:string[]}}
 */
export function validateNavItem(item, seen = { ids: new Set(), routes: new Set() }) {
  const errors = [];
  if (!item || typeof item !== "object") return { ok: false, errors: ["nav item must be an object"] };
  if (!isNonEmptyString(item.id)) errors.push("nav item id is required (non-empty string)");
  else if (seen.ids.has(item.id)) errors.push(`duplicate nav id: ${item.id}`);
  if (!isLocalized(item.label)) errors.push('nav item label must be { en, fa } with non-empty strings');
  if (!isNonEmptyString(item.icon)) errors.push("nav item icon is required");
  else if (!ICON_ALLOWLIST.includes(item.icon)) {
    errors.push(`unknown icon "${item.icon}"; allowed: ${ICON_ALLOWLIST.join(", ")}`);
  }
  if (typeof item.order !== "number" || !Number.isFinite(item.order)) {
    errors.push("nav item order must be a finite number");
  }
  if (item.visible != null && typeof item.visible !== "boolean") errors.push("nav item visible must be a boolean");
  if (!isNonEmptyString(item.route)) errors.push("nav item route is required (e.g. /agents)");
  else if (!item.route.startsWith("/")) errors.push(`nav item route must start with "/": ${item.route}`);
  else if (seen.routes.has(item.route)) errors.push(`duplicate route: ${item.route}`);
  if (!isNonEmptyString(item.renderer)) errors.push("nav item renderer is required");
  else if (!RENDERER_ALLOWLIST.includes(item.renderer)) {
    errors.push(`unknown renderer "${item.renderer}"; allowed: ${RENDERER_ALLOWLIST.join(", ")}`);
  }
  if (item.capabilities != null && !Array.isArray(item.capabilities)) {
    errors.push("nav item capabilities must be an array");
  }
  if (item.permissions != null && !Array.isArray(item.permissions)) {
    errors.push("nav item permissions must be an array");
  }
  return { ok: errors.length === 0, errors };
}

/**
 * Validate a whole navigation manifest. Collects every error.
 * @returns {{ok:boolean, errors:string[]}}
 */
export function validateManifest(manifest) {
  const errors = [];
  if (!manifest || typeof manifest !== "object") {
    return { ok: false, errors: ["manifest must be an object"] };
  }
  if (manifest.schemaVersion !== MANIFEST_SCHEMA_VERSION) {
    errors.push(`unsupported manifest schemaVersion: ${String(manifest.schemaVersion)}`);
  }
  if (!Array.isArray(manifest.items)) {
    return { ok: false, errors: [...errors, "manifest.items must be an array"] };
  }
  const seen = { ids: new Set(), routes: new Set() };
  manifest.items.forEach((item, i) => {
    const res = validateNavItem(item, seen);
    if (item && item.id) seen.ids.add(item.id);
    if (item && item.route) seen.routes.add(item.route);
    if (!res.ok) errors.push(...res.errors.map((e) => `items[${i}]: ${e}`));
  });
  return { ok: errors.length === 0, errors };
}

/**
 * Validate standard page definitions. Every page must reference a
 * known renderer; routes must be unique.
 * @returns {{ok:boolean, errors:string[]}}
 */
export function validatePages(pages) {
  const errors = [];
  if (!Array.isArray(pages)) return { ok: false, errors: ["pages must be an array"] };
  const routes = new Set();
  pages.forEach((page, i) => {
    if (!page || typeof page !== "object") {
      errors.push(`pages[${i}]: must be an object`);
      return;
    }
    if (!isNonEmptyString(page.id)) errors.push(`pages[${i}]: id is required`);
    if (!isNonEmptyString(page.route)) errors.push(`pages[${i}]: route is required`);
    else if (!page.route.startsWith("/")) errors.push(`pages[${i}]: route must start with "/": ${page.route}`);
    else if (routes.has(page.route)) errors.push(`pages[${i}]: duplicate route: ${page.route}`);
    else routes.add(page.route);
    if (!isNonEmptyString(page.renderer)) errors.push(`pages[${i}]: renderer is required`);
    else if (!RENDERER_ALLOWLIST.includes(page.renderer)) {
      errors.push(`pages[${i}]: unknown renderer "${page.renderer}"`);
    }
    if (!isLocalized(page.title)) errors.push(`pages[${i}]: title must be { en, fa }`);
    if (page.props != null && typeof page.props !== "object") {
      errors.push(`pages[${i}]: props must be an object`);
    }
  });
  return { ok: errors.length === 0, errors };
}

/** Sort navigation items by their declared order. */
export function sortNavItems(manifest) {
  return [...manifest.items].sort((a, b) => a.order - b.order);
}

/**
 * Capability gating. An entry is `available` only when every required
 * capability is supported AND every required permission is granted.
 * Unavailable entries carry a readable reason.
 *
 * NOTE: hiding an entry here is a UI concern only — the backend must
 * enforce authorization.
 */
export function resolveNavItems(manifest, { capabilities = [], permissions = [] } = {}) {
  return sortNavItems(manifest).map((item) => {
    const missingCaps = (item.capabilities || []).filter((c) => !capabilities.includes(c));
    const missingPerms = (item.permissions || []).filter((p) => !permissions.includes(p));
    const available = missingCaps.length === 0 && missingPerms.length === 0;
    return {
      ...item,
      visible: item.visible !== false,
      available,
      // Structured reasons let the UI localize the explanation;
      // `unavailableReason` stays as the readable model-level text.
      missingCapabilities: missingCaps,
      missingPermissions: missingPerms,
      unavailableReason: !available
        ? missingCaps.length > 0
          ? `missing capabilities: ${missingCaps.join(", ")}`
          : `missing permissions: ${missingPerms.join(", ")}`
        : null,
    };
  });
}

/**
 * The navigation the user actually sees: resolved items with
 * visibility applied. A hidden item is NOT in the navigation —
 * but its manifest entry is untouched (data is never deleted).
 */
export function visibleNavItems(resolved) {
  return resolved.filter((item) => item.visible);
}

/**
 * Resolve a route to a renderable page. Source of truth is the
 * validated manifest + page definitions — never executable code:
 *   1. the navigation item for the route (renderer + label), and/or
 *   2. the standard page for the route (title + props).
 * Falls back to the nav item's renderer when no page exists.
 * Returns { ok:false, error } for unknown routes — readable, safe.
 */
export function resolvePage(route, manifest, pages) {
  const items =
    manifest && Array.isArray(manifest.items) ? manifest.items : [];
  const pageList = Array.isArray(pages) ? pages : [];
  const item = items.find((i) => i && i.route === route) || null;
  const page = pageList.find((p) => p && p.route === route) || null;
  if (!item && !page) {
    return { ok: false, error: `no page is configured for route "${route}"`, route };
  }
  return {
    ok: true,
    route,
    page: {
      id: (page && page.id) || (item && item.id) || route,
      route,
      renderer: (page && page.renderer) || (item && item.renderer) || null,
      title: (page && page.title) || (item && item.label) || { en: route, fa: route },
      props: (page && page.props) || {},
    },
    item,
    pageDef: page,
  };
}

/**
 * Supported page templates for the customization UI. Pure data —
 * no executable code. Creating a page from a template yields a
 * page definition PLUS its navigation entry (both as draft ops).
 */
export const PAGE_TEMPLATES = [
  {
    id: "tpl-connections",
    label: { en: "Connections table", fa: "جدول اتصال‌ها" },
    icon: "network",
    route: "/connections",
    renderer: "resource-table",
    props: { source: "connections" },
  },
  {
    id: "tpl-runs",
    label: { en: "Runs timeline", fa: "خط‌زمانی اجراها" },
    icon: "history",
    route: "/runs",
    renderer: "timeline",
    props: { source: "runs" },
  },
  {
    id: "tpl-agent-detail",
    label: { en: "Agent detail", fa: "جزئیات عامل" },
    icon: "bot",
    route: "/agent-detail",
    renderer: "resource-detail",
    props: { source: "agent", id: "dsh" },
  },
  {
    id: "tpl-workspace-info",
    label: { en: "Workspace info", fa: "اطلاعات فضای کاری" },
    icon: "layers",
    route: "/workspace-info",
    renderer: "schema-form",
    props: {
      fields: [
        { id: "storageKey", label: { en: "Storage key", fa: "کلید ذخیره‌سازی" }, type: "text", value: "agentos-workspace-v1" },
        { id: "schemaVersion", label: { en: "Schema version", fa: "نسخه اسکیما" }, type: "text", value: "1" },
        { id: "dataLabel", label: { en: "Data label", fa: "برچسب داده" }, type: "text", value: "MOCK / demo" },
        { id: "simulated", label: { en: "Simulated adapter", fa: "آداپتر شبیه‌سازی‌شده" }, type: "toggle", value: true },
      ],
    },
  },
];

/**
 * Build the draft ops for "create a page from a template":
 * a page definition and its navigation entry. Pure.
 * @returns {{page:object, item:object}}
 */
export function pageFromTemplate(template, { order, idPrefix = "nav-" } = {}) {
  const route = template.route;
  const suffix = route.replace(/^\//, "") || "page";
  return {
    page: {
      id: `page-${suffix}`,
      route,
      renderer: template.renderer,
      title: { ...template.label },
      props: JSON.parse(JSON.stringify(template.props || {})),
    },
    item: {
      id: `${idPrefix}${suffix}`,
      icon: template.icon,
      route,
      renderer: template.renderer,
      order,
      label: { ...template.label },
      visible: true,
      capabilities: [],
      permissions: [],
    },
  };
}

/**
 * Resolve a renderer name against the registry. Returns a safe error
 * descriptor for unknown names — never throws, never evals.
 */
export function resolveRenderer(name, registry) {
  if (typeof name !== "string" || !RENDERER_ALLOWLIST.includes(name)) {
    return {
      ok: false,
      error: `unknown page renderer "${String(name)}"; registered: ${Object.keys(registry || {}).join(", ")}`,
    };
  }
  const component = registry ? registry[name] : null;
  if (!component) {
    return { ok: false, error: `renderer "${name}" is not registered in the renderer registry` };
  }
  return { ok: true, component };
}
