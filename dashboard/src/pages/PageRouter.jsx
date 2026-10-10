// The page router (skill 07): route → validated manifest/pages →
// renderer name → registry component.
//
// Rules:
//   - unknown route        → readable "page not found" panel
//   - unknown renderer     → readable renderer error panel
//   - never eval, never dynamic script loading, never a crash
// Every page carries MOCK/demo data; the header says so.

import { resolvePage, resolveRenderer } from "../model/manifest.js";
import { RENDERER_REGISTRY } from "./registry.js";

export default function PageRouter({
  route,
  manifest,
  pages,
  t,
  lang,
  rtl,
  ctx,
  draftBar,
  tools,
  onNavigate,
}) {
  const resolved = resolvePage(route, manifest, pages);

  const back = (
    <button
      type="button"
      onClick={() => onNavigate("/home")}
      className="chip mt-4"
    >
      {t.backToCanvas}
    </button>
  );

  let body;
  if (!resolved.ok) {
    body = (
      <div>
        <div className="text-[16px] text-[#ffd166]">{t.pageNotFound}</div>
        <p className="mt-2 text-[14px] text-[var(--mu)]">
          {t.pageNotFoundHint}: <span className="mono">{route}</span>
        </p>
        {back}
      </div>
    );
  } else {
    const r = resolveRenderer(resolved.page.renderer, RENDERER_REGISTRY);
    if (!r.ok) {
      body = (
        <div>
          <div className="text-[16px] text-[#ff5c7a]">{t.rendererError}</div>
          <p className="mono mt-2 whitespace-pre-wrap text-[13px] text-[var(--mu)]">
            {r.error}
          </p>
          <p className="mt-2 text-[13px] text-[var(--mu)]">{t.rendererErrorHint}</p>
          {back}
        </div>
      );
    } else {
      const C = r.component;
      body = (
        <C
          page={resolved.page}
          t={t}
          lang={lang}
          rtl={rtl}
          ctx={ctx}
          onNavigate={onNavigate}
        />
      );
    }
  }

  const title = resolved.ok ? resolved.page.title : null;
  return (
    <section
      dir={rtl ? "rtl" : "ltr"}
      className="glass hud-frame relative flex min-h-[700px] flex-col overflow-hidden lg:col-span-2 lg:row-span-2"
    >
      <div className="relative z-10 flex flex-wrap items-end gap-x-4 gap-y-1 px-6 pt-5">
        {title && (
          <h2
            className="disp text-[32px] leading-none text-[var(--sun2)]"
            style={{ textShadow: "0 0 18px rgba(56,232,255,.45)" }}
          >
            {labelOf(title, lang)}
          </h2>
        )}
        <span className="mock-tag">MOCK</span>
        <span className="mono ms-auto pb-0.5 text-[14px] text-[var(--mu)]">
          {route}
        </span>
      </div>
      {/* The shared draft bar AND the workspace tools (export /
          import / reset) stay reachable on every route: the draft
          flow (skill 04) and the workspace lifecycle are global
          actions, not canvas-only ones (phase 8 finding). */}
      {(draftBar || tools) && (
        <div className="relative z-10 flex flex-wrap items-center gap-2 border-b border-[var(--line)] px-6 py-3">
          {draftBar}
          {tools && <div className="ms-auto">{tools}</div>}
        </div>
      )}
      <div className="relative z-10 flex-1 overflow-auto px-6 pb-6 pt-4">
        {body}
      </div>
    </section>
  );
}

function labelOf(loc, lang) {
  return (loc && (loc[lang] || loc.en)) || "";
}
