// Navigation customization UI (skill 07).
//
// Every change here is a DRAFT change under skill-04 rules:
// nothing applies instantly. Entries and pages are validated
// (model validators) before they even reach the draft, the
// adapter validates again on apply, and the result lands only
// after the user presses Apply in the draft bar.
//
// Manifests are DATA: labels, routes, icon/renderer names from
// allowlists. No executable code is ever accepted or stored.

import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Eye, EyeOff, Plus, X } from "lucide-react";
import {
  ICON_ALLOWLIST,
  PAGE_TEMPLATES,
  RENDERER_ALLOWLIST,
  pageFromTemplate,
  validateNavItem,
  validatePages,
} from "../model/manifest.js";
import { iconFor } from "../pages/icons.js";

const EMPTY_FORM = { id: "", en: "", fa: "", icon: "layers", route: "", renderer: "resource-table" };

export default function NavCustomizer({
  t,
  lang,
  manifest,
  pages,
  onAddNavItem,
  onMoveNav,
  onToggleVisible,
  onCreatePage,
  onClose,
}) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [errors, setErrors] = useState([]);
  const [templateId, setTemplateId] = useState(PAGE_TEMPLATES[0].id);

  // Escape closes the panel (topmost overlay).
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const items = [...manifest.items].sort((a, b) => a.order - b.order);
  const maxOrder = items.reduce((m, i) => Math.max(m, i.order), 0);

  const seenFor = () => ({
    ids: new Set(items.map((i) => i.id)),
    routes: new Set(items.map((i) => i.route)),
  });

  const submitEntry = () => {
    const item = {
      id: form.id.trim(),
      label: { en: form.en.trim(), fa: form.fa.trim() },
      icon: form.icon,
      route: form.route.trim(),
      renderer: form.renderer,
      order: maxOrder + 10,
      visible: true,
      capabilities: [],
      permissions: [],
    };
    // Validate BEFORE drafting; the adapter re-validates on apply.
    const check = validateNavItem(item, seenFor());
    if (!check.ok) {
      setErrors(check.errors);
      return;
    }
    setErrors([]);
    onAddNavItem(item);
    setForm(EMPTY_FORM);
    setShowForm(false);
  };

  const createFromTemplate = () => {
    const tpl = PAGE_TEMPLATES.find((x) => x.id === templateId);
    if (!tpl) return;
    const { page, item } = pageFromTemplate(tpl, { order: maxOrder + 10 });
    const navCheck = validateNavItem(item, seenFor());
    const pageCheck = validatePages([...pages, page]);
    const all = [...navCheck.errors, ...pageCheck.errors];
    if (all.length) {
      setErrors(all);
      return;
    }
    setErrors([]);
    onCreatePage(page, item);
  };

  const setField = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(2,8,16,.62)] p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="presentation"
    >
      <div
        className="glass rise max-h-[88vh] w-full max-w-[600px] overflow-auto p-5"
        role="dialog"
        aria-label={t.navCustomize}
      >
        <div className="flex items-center gap-3">
          <h3 className="disp text-[22px] leading-none text-[var(--sun2)]">
            {t.navCustomize}
          </h3>
          <span className="mock-tag">MOCK</span>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.cancel}
            className="ms-auto grid h-8 w-8 place-items-center rounded-full border border-[var(--line)] text-[var(--mu)] transition hover:text-[var(--sun2)]"
          >
            <X size={15} />
          </button>
        </div>
        <p className="mt-2 text-[13px] text-[var(--mu)]">{t.navDraftNote}</p>

        {/* ---- Entries: reorder + show/hide ---- */}
        <div className="mt-4 disp text-[16px]">{t.navEntries}</div>
        <ul className="mt-2 flex flex-col gap-1.5">
          {items.map((item, i) => {
            const Icon = iconFor(item.icon);
            return (
              <li
                key={item.id}
                className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[rgba(2,10,20,.45)] px-3 py-2"
                style={{ opacity: item.visible === false ? 0.55 : 1 }}
              >
                <button
                  type="button"
                  onClick={() => onMoveNav(item.id, -1)}
                  disabled={i === 0}
                  aria-label={t.moveUp}
                  title={t.moveUp}
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[var(--mu)] transition hover:text-[var(--sun2)] disabled:opacity-30"
                >
                  <ArrowUp size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => onMoveNav(item.id, 1)}
                  disabled={i === items.length - 1}
                  aria-label={t.moveDown}
                  title={t.moveDown}
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[var(--mu)] transition hover:text-[var(--sun2)] disabled:opacity-30"
                >
                  <ArrowDown size={14} />
                </button>
                <Icon size={15} className="shrink-0 text-[var(--sun)]" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px]">
                    {item.label[lang]}
                  </span>
                  <span className="mono block truncate text-[12px] text-[var(--mu)]">
                    {item.route} · {item.renderer}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => onToggleVisible(item.id, item.visible === false)}
                  aria-label={item.visible === false ? t.showEntry : t.hideEntry}
                  title={item.visible === false ? t.showEntry : t.hideEntry}
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[var(--mu)] transition hover:text-[var(--sun2)]"
                >
                  {item.visible === false ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </li>
            );
          })}
        </ul>

        {/* ---- Create a page from a template ---- */}
        <div className="mt-5 disp text-[16px]">{t.createPageFromTemplate}</div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            className="min-w-[200px] flex-1 rounded-xl border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] outline-none"
          >
            {PAGE_TEMPLATES.map((tpl) => (
              <option key={tpl.id} value={tpl.id}>
                {tpl.label[lang]} — {tpl.route}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={createFromTemplate}
            className="btn-core flex items-center gap-1.5 rounded-full px-4 py-2 text-[14px] font-semibold transition hover:brightness-110"
          >
            <Plus size={14} />
            {t.createPage}
          </button>
        </div>

        {/* ---- Add a navigation entry ---- */}
        <div className="mt-5 flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setShowForm((s) => !s);
              setErrors([]);
            }}
            className="chip"
            data-on={showForm}
            aria-expanded={showForm}
          >
            <Plus size={13} />
            {t.addNavEntry}
          </button>
        </div>
        {showForm && (
          <div className="mt-3 grid grid-cols-1 gap-3 rounded-xl border border-[var(--line)] p-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-[13px] text-[var(--mu)]">
              {t.fieldId}
              <input
                value={form.id}
                onChange={setField("id")}
                placeholder="audit-log"
                className="mono rounded-lg border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] text-[#e9fdff] outline-none"
              />
            </label>
            <label className="flex flex-col gap-1 text-[13px] text-[var(--mu)]">
              {t.fieldRoute}
              <input
                value={form.route}
                onChange={setField("route")}
                placeholder="/audit-log"
                className="mono rounded-lg border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] text-[#e9fdff] outline-none"
              />
            </label>
            <label className="flex flex-col gap-1 text-[13px] text-[var(--mu)]">
              {t.fieldLabelEn}
              <input
                value={form.en}
                onChange={setField("en")}
                placeholder="Audit log"
                className="rounded-lg border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] text-[#e9fdff] outline-none"
              />
            </label>
            <label className="flex flex-col gap-1 text-[13px] text-[var(--mu)]">
              {t.fieldLabelFa}
              <input
                value={form.fa}
                onChange={setField("fa")}
                placeholder="گزارش ممیزی"
                dir="rtl"
                className="rounded-lg border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] text-[#e9fdff] outline-none"
              />
            </label>
            <label className="flex flex-col gap-1 text-[13px] text-[var(--mu)]">
              {t.fieldIcon}
              <select
                value={form.icon}
                onChange={setField("icon")}
                className="rounded-lg border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] outline-none"
              >
                {ICON_ALLOWLIST.map((ic) => (
                  <option key={ic} value={ic}>
                    {ic}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[13px] text-[var(--mu)]">
              {t.fieldRenderer}
              <select
                value={form.renderer}
                onChange={setField("renderer")}
                className="rounded-lg border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] outline-none"
              >
                {RENDERER_ALLOWLIST.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-2 sm:col-span-2">
              <button
                type="button"
                onClick={submitEntry}
                className="btn-core rounded-full px-4 py-2 text-[14px] font-semibold transition hover:brightness-110"
              >
                {t.navAdd}
              </button>
              <button type="button" onClick={() => setShowForm(false)} className="chip">
                {t.cancel}
              </button>
            </div>
          </div>
        )}

        {errors.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1 rounded-xl border border-[rgba(255,92,122,.35)] p-3 text-[13px] text-[#ff5c7a]">
            <li className="font-semibold">{t.formInvalid}</li>
            {errors.map((e, i) => (
              <li key={`fe-${i}`} className="mono text-[12px]">
                • {e}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
