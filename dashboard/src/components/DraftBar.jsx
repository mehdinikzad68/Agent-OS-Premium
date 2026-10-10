// Mode toggle (Observe / Edit), draft status with a readable
// review panel, apply / discard, and undo / redo.
import { useState } from "react";
import {
  Check,
  Eye,
  ListChecks,
  Pencil,
  Redo2,
  Trash2,
  Undo2,
} from "lucide-react";

export default function DraftBar({
  t,
  mode,
  onMode,
  summary,
  hasPending,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onApply,
  onDiscard,
  applying,
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative flex flex-wrap items-center gap-2">
      <div
        className="flex rounded-full border border-[var(--line)] bg-[rgba(2,10,20,.6)] p-0.5"
        role="group"
        aria-label={t.modeLabel}
      >
        <button
          type="button"
          onClick={() => onMode("observe")}
          className="chip !border-0 rounded-full"
          data-on={mode === "observe"}
          aria-pressed={mode === "observe"}
        >
          <Eye size={13} />
          {t.mode.observe}
        </button>
        <button
          type="button"
          onClick={() => onMode("edit")}
          className="chip !border-0 rounded-full"
          data-on={mode === "edit"}
          aria-pressed={mode === "edit"}
        >
          <Pencil size={13} />
          {t.mode.edit}
        </button>
      </div>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="chip"
        data-on={open}
        aria-expanded={open}
      >
        <ListChecks size={13} />
        {hasPending
          ? `${summary.total} ${t.unappliedChanges}`
          : summary.rejectedChanges.length > 0
            ? `${summary.rejectedChanges.length} ${t.rejectedChangesShort}`
            : t.allApplied}
      </button>

      <button
        type="button"
        onClick={onApply}
        disabled={!hasPending || applying}
        className="btn-core flex items-center gap-1.5 rounded-full px-3 py-2 text-[14px] font-semibold disabled:opacity-40"
      >
        <Check size={14} />
        {applying ? t.applying : t.apply}
      </button>

      <button
        type="button"
        onClick={onDiscard}
        disabled={!hasPending && summary.rejectedChanges.length === 0}
        className="chip flex items-center gap-1.5 disabled:opacity-40"
      >
        <Trash2 size={13} />
        {t.discard}
      </button>

      <button
        type="button"
        onClick={onUndo}
        disabled={!canUndo}
        aria-label={t.undo}
        title={t.undo}
        className="grid h-8 w-8 place-items-center rounded-full border border-[var(--line)] text-[var(--mu)] transition hover:text-[var(--sun2)] disabled:opacity-40"
      >
        <Undo2 size={14} />
      </button>
      <button
        type="button"
        onClick={onRedo}
        disabled={!canRedo}
        aria-label={t.redo}
        title={t.redo}
        className="grid h-8 w-8 place-items-center rounded-full border border-[var(--line)] text-[var(--mu)] transition hover:text-[var(--sun2)] disabled:opacity-40"
      >
        <Redo2 size={14} />
      </button>

      {open && (
        <div className="glass rise absolute top-full start-0 z-40 mt-2 w-[320px] p-4">
          <div className="disp text-[16px]">{t.review}</div>
          {/* Rejected ops are reviewable EVEN when nothing is
              pending anymore (skill 08 acceptance: a partial apply
              keeps showing its partial status and the reasons —
              "all applied" would be a false statement). */}
          {summary.total === 0 && summary.rejectedChanges.length === 0 ? (
            <div className="mt-2 text-[14px] text-[var(--mu)]">{t.allApplied}</div>
          ) : (
            <ul className="mt-2 flex flex-col gap-1.5 text-[14px]">
              {summary.addedEntities.map((e) => (
                <li key={`ae-${e.id}`} className="text-[#c4f7dc]">
                  ＋ {t.summary.addedEntities}: {e.name}
                </li>
              ))}
              {summary.removedEntities.map((id) => (
                <li key={`re-${id}`} className="text-[#ffc0ca]">
                  － {t.summary.removedEntities}: {id}
                </li>
              ))}
              {summary.addedConnections.map((c) => (
                <li key={`ac-${c.id}`} className="text-[#c4f7dc]">
                  ＋ {t.summary.addedConnections}: {c.from} → {c.to} ({c.type})
                </li>
              ))}
              {summary.removedConnections.map((id) => (
                <li key={`rc-${id}`} className="text-[#ffc0ca]">
                  － {t.summary.removedConnections}: {id}
                </li>
              ))}
              {summary.changedConnectionStates.map((c) => (
                <li key={`cs-${c.connectionId}`} className="text-[#ffd166]">
                  ◆ {t.summary.changedConnectionStates}: {c.connectionId} → {c.state}
                </li>
              ))}
              {summary.changedPermissions.map((p) => (
                <li
                  key={`cp-${p.agentId}-${p.scope}`}
                  className="text-[#ffd166]"
                >
                  ◆ {t.summary.changedPermissions}: {p.agentId} / {p.scope}
                </li>
              ))}
              {summary.addedNavItems.map((e) => (
                <li key={`an-${e.id}`} className="text-[#c4f7dc]">
                  ＋ {t.summary.addedNavItems}: {e.id} → {e.route}
                </li>
              ))}
              {summary.movedNavItems.map((m) => (
                <li key={`mn-${m.navId}`} className="text-[#ffd166]">
                  ◆ {t.summary.movedNavItems}: {m.navId} (Δ
                  {m.delta > 0 ? "+1" : "-1"})
                </li>
              ))}
              {summary.navVisibility.map((v) => (
                <li key={`nv-${v.navId}`} className="text-[#ffd166]">
                  ◆ {t.summary.navVisibility}: {v.navId} →{" "}
                  {v.visible ? t.enabled : t.disabled}
                </li>
              ))}
              {summary.addedPages.map((p) => (
                <li key={`ap-${p.id}`} className="text-[#c4f7dc]">
                  ＋ {t.summary.addedPages}: {p.id} ({p.route})
                </li>
              ))}
              {summary.layoutOnly.map((item, i) => (
                <li key={`lo-${i}`} className="text-[var(--mu)]">
                  ▽ {t.summary.layoutOnly}: {item}
                </li>
              ))}
              {summary.rejectedChanges.length > 0 && (
                <li className="mt-1 text-[12px] font-semibold text-[#ff5c7a]">
                  ✖ {t.rejectedChanges}
                </li>
              )}
              {summary.rejectedChanges.map((c) => (
                <li key={`rj-${c.opId}`} className="text-[#ff5c7a]">
                  {c.op} — {c.reason || "—"}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 border-t border-[var(--line)] pt-2 text-[12px] text-[var(--mu)]">
            {t.applySimulated}
          </div>
        </div>
      )}
    </div>
  );
}
