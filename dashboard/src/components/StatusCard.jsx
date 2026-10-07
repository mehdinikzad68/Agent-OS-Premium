// Minified name in bundle: mx.
import { Trash2, X } from "lucide-react";
import { STATUS_COLOR, SUN } from "../scene/colors.js";

export default function StatusCard({ a, t, rtl, lang, onClose, onRemove }) {
  const col = a.id === "hermes" ? SUN : STATUS_COLOR[a.status];
  return (
    <div className="absolute inset-x-0 top-2 z-20 flex justify-center pointer-events-none">
      <div dir={rtl ? "rtl" : "ltr"} className="rise glass pointer-events-auto relative w-[300px] px-4 py-3">
        <button onClick={onClose} aria-label="Close" className="absolute top-2.5 text-[var(--mu)] hover:text-white ltr:right-2.5 rtl:left-2.5">
          <X size={16} />
        </button>
        <div className="flex items-center gap-2">
          <i className="dotlive h-2.5 w-2.5 rounded-full" style={{ background: col, color: col }} />
          <span className="disp text-[20px] leading-none">{a.name}</span>
          <span className="text-[14px]" style={{ color: STATUS_COLOR[a.status] }}>
            {t.legend[a.status]}
          </span>
        </div>
        <div className="mt-1 text-[14px] text-[var(--mu)]">{a.id === "hermes" ? t.brain : a.sub[lang]}</div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-[14px] text-[var(--mu)]">
          <div>
            {t.lastSeen}
            <div className="mono text-[14px] text-[var(--tx)]">{a.seen}</div>
          </div>
          <div>
            {t.tokens}
            <div className="mono text-[14px] text-[var(--tx)]">{a.tok}</div>
          </div>
          <div>
            {t.load}
            <div className="mono text-[14px] text-[var(--tx)]">
              {a.load}%
            </div>
          </div>
        </div>
        <div className="mt-2 h-1 rounded bg-[#0b2233]">
          <div className="h-full rounded" style={{ width: `${a.load}%`, background: col, boxShadow: `0 0 8px ${col}` }} />
        </div>
        {onRemove && (
          <button
            onClick={onRemove}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-full border border-[rgba(255,92,122,.4)] py-2 text-[14px] text-[#ffc0ca] transition hover:bg-[rgba(255,92,122,.12)]"
          >
            <Trash2 size={14} />
            {t.remove}
          </button>
        )}
      </div>
    </div>
  );
}
