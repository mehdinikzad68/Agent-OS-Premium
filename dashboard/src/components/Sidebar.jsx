// Declarative navigation generator (skill 07): entries come from
// the VALIDATED manifest — order, visibility and capability
// gating all resolve from data, never from fixed JSX arrays.
//
// IMPORTANT: hiding or disabling a nav entry is a UI concern
// only. It is NOT authorization — the backend must enforce
// permissions on every action regardless of what the UI shows.

import { SlidersHorizontal, CircleQuestionMark } from "lucide-react";
import { resolveNavItems, visibleNavItems } from "../model/manifest.js";
import { iconFor } from "../pages/icons.js";

export default function Sidebar({
  t,
  lang,
  manifest,
  activeRoute,
  onNavigate,
  capabilities = [],
  permissions = [],
  badges = {},
  onCustomize,
}) {
  const resolved = resolveNavItems(manifest, { capabilities, permissions });
  // Hidden items are not rendered — but their manifest entries
  // stay untouched (data is never deleted by hiding).
  const items = visibleNavItems(resolved);

  return (
    <nav className="glass scroll flex gap-1 overflow-x-auto p-2 lg:row-span-2 lg:flex-col lg:overflow-visible">
      {items.map((item) => {
        const Icon = iconFor(item.icon);
        const on = activeRoute === item.route;
        const why = !item.available
          ? item.missingCapabilities.length > 0
            ? `${t.missingCaps}: ${item.missingCapabilities.join(", ")}`
            : `${t.missingPerms}: ${item.missingPermissions.join(", ")}`
          : null;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => item.available && onNavigate(item.route)}
            disabled={!item.available}
            title={why || item.label[lang]}
            aria-current={on ? "page" : undefined}
            className="navi relative flex shrink-0 items-center gap-3 rounded-xl px-3 py-2.5 text-start disabled:cursor-not-allowed"
            style={{
              background: on
                ? "linear-gradient(90deg,rgba(56,232,255,.14),rgba(56,232,255,.02))"
                : "transparent",
              color: !item.available
                ? "var(--mu)"
                : on
                  ? "#e9fdff"
                  : "var(--mu)",
              opacity: item.available ? 1 : 0.75,
            }}
          >
            {on && (
              <span
                className="absolute inset-y-2 w-[3px] rounded-full bg-[var(--sun)] ltr:left-0 rtl:right-0"
                style={{ boxShadow: "0 0 10px #38e8ff" }}
              />
            )}
            <Icon size={18} className="shrink-0" />
            <span className="flex min-w-0 flex-col items-start">
              <span className="truncate">{item.label[lang]}</span>
              {why && <span className="nav-why">⚠ {why}</span>}
            </span>
            {badges[item.id] != null && badges[item.id] > 0 && (
              <span className="mono ms-auto rounded-full bg-[rgba(255,154,82,.15)] px-2 text-[13px] text-[var(--await)]">
                {badges[item.id]}
              </span>
            )}
          </button>
        );
      })}
      {/* Both actions are visible at EVERY viewport (phase 8
          finding: hiding them under `hidden lg:flex` made nav
          customization unreachable on phones). `lg:mt-auto` keeps
          the bottom-anchor only in the wide column layout. */}
      <button
        type="button"
        onClick={onCustomize}
        className="navi flex items-center gap-3 rounded-xl px-3 py-2.5 text-start text-[var(--mu)] transition hover:text-[var(--sun2)] lg:mt-auto"
        title={t.navCustomize}
      >
        <SlidersHorizontal size={18} />
        {t.navCustomize}
      </button>
      <button
        type="button"
        className="navi flex items-center gap-3 rounded-xl px-3 py-2.5 text-start text-[var(--mu)]"
      >
        <CircleQuestionMark size={18} />
        {t.help}
      </button>
    </nav>
  );
}
