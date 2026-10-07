// Minified name in bundle: cx.
import { Radio } from "lucide-react";

export default function Header({ t, lang, setLang }) {
  return (
    <header className="flex flex-wrap items-center gap-4 border-b border-[var(--line)] bg-[rgba(2,8,16,.75)] px-5 py-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <span className="relative grid h-10 w-10 place-items-center">
          <span
            className="absolute inset-0 rounded-full"
            style={{ background: "radial-gradient(circle, #e8feff 0 14%, #38e8ff 30%, rgba(56,232,255,.18) 56%, transparent 72%)" }}
          />
          <span className="absolute inset-[-2px] rounded-full border border-[rgba(56,232,255,.45)]" style={{ transform: "scaleY(.32)" }} />
        </span>
        <span
          className="disp f-en text-[24px] leading-none text-[var(--sun2)]"
          style={{ fontFamily: "'Chakra Petch',sans-serif", textTransform: "uppercase", letterSpacing: ".08em" }}
        >
          {t.brand}
        </span>
        <span className="h-6 w-px bg-[var(--line)]" />
        <span className="text-[16px] text-[var(--mu)]">{t.section}</span>
      </div>
      <div className="ms-auto flex items-center gap-3">
        <div className="hidden items-center gap-2 rounded-full border border-[var(--line)] px-3 py-1.5 md:flex">
          <Radio size={14} className="text-[var(--ok)]" />
          <span className="text-[14px] text-[var(--mu)]">{t.mission}</span>
          <span className="mono text-[14px]">wp-bioscentiran</span>
        </div>
        <span className="flex items-center gap-2 text-[14px] text-[var(--sun)]">
          <i className="dotlive h-2 w-2 rounded-full bg-[var(--sun)] text-[var(--sun)]" />
          {t.live}
        </span>
        <div className="flex items-center gap-2.5 border-s border-[var(--line)] ps-3">
          <div className="grid h-9 w-9 place-items-center rounded-full bg-[linear-gradient(135deg,#0f6f8a,#06202e)] text-[14px] font-semibold ring-1 ring-[var(--line)]">
            MS
          </div>
          <div className="hidden leading-tight sm:block">
            <div className="text-[14px] font-medium">Martin Sanchez</div>
            <div className="text-[14px] text-[var(--mu)]">{t.approver}</div>
          </div>
        </div>
        <button
          onClick={() => setLang(lang === "en" ? "fa" : "en")}
          aria-label="Toggle language"
          className="flex h-9 items-center rounded-full border border-[rgba(56,232,255,.45)] bg-[rgba(56,232,255,.08)] px-4 text-[14px] font-semibold text-[var(--sun2)] transition hover:bg-[rgba(56,232,255,.16)]"
        >
          <span className={lang === "en" ? "f-fa" : "f-en"}>{t.lang}</span>
        </button>
      </div>
    </header>
  );
}
