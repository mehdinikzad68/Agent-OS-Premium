// Approval gate (minified names in bundle: hx = Gate, xx = GateBody).
import { useEffect, useRef, useState } from "react";
import { Check, EyeOff, ShieldAlert, TriangleAlert, X } from "lucide-react";
import { APPROVER } from "../data.js";

const HOLD_MS = 1200;

export default function Gate({ approvals, t, lang, decide }) {
  const [idx, setIdx] = useState(0);
  const cur = approvals[Math.min(idx, approvals.length - 1)];
  return (
    <aside className={`glass flex flex-col overflow-hidden ${cur ? "glass-flare" : ""}`}>
      <div className="flex items-center gap-2.5 border-b border-[var(--line)] px-5 py-4">
        <ShieldAlert size={20} className={cur ? "text-[var(--await)]" : "text-[var(--ok)]"} />
        <h2 className="disp text-[22px] leading-none">{t.gate}</h2>
        <span className="mono ms-auto text-[14px] text-[var(--await)]">{approvals.length}</span>
        <span className="text-[14px] text-[var(--mu)]">{t.queue}</span>
      </div>
      {approvals.length > 1 && (
        <div className="flex gap-2 px-5 pt-3">
          {approvals.map((g, i) => (
            <button
              key={g.id}
              onClick={() => setIdx(i)}
              className="flex items-center gap-2 rounded-full border px-3 py-1.5 transition"
              style={{ borderColor: cur?.id === g.id ? (g.tier === 3 ? "#ff5c7a" : "#ff9a52") : "var(--line)" }}
            >
              <span className="mono text-[13px] font-semibold" style={{ color: g.tier === 3 ? "#ff5c7a" : "#ff9a52" }}>
                T{g.tier}
              </span>
              <span className="mono text-[13px]">{g.id}</span>
            </button>
          ))}
        </div>
      )}
      {cur ? (
        <GateBody
          key={cur.id}
          g={cur}
          t={t}
          lang={lang}
          decide={(ok) => {
            decide(cur, ok);
            setIdx(0);
          }}
        />
      ) : (
        <div className="grid flex-1 place-items-center p-8 text-center">
          <div>
            <div
              className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full border border-[var(--ok)] text-[var(--ok)]"
              style={{ boxShadow: "0 0 24px rgba(95,240,168,.35)" }}
            >
              <Check size={22} />
            </div>
            <div className="disp text-[22px]">{t.empty}</div>
            <div className="mt-1 text-[var(--mu)]">{t.emptySub}</div>
          </div>
        </div>
      )}
    </aside>
  );
}

export function GateBody({ g, t, lang, decide }) {
  const [hold, setHold] = useState(0);
  const raf = useRef();
  const t0 = useRef(0);

  const begin = () => {
    t0.current = performance.now();
    const step = () => {
      const k = Math.min(1, (performance.now() - t0.current) / HOLD_MS);
      setHold(k);
      if (k >= 1) return decide(true);
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
  };
  const end = () => {
    cancelAnimationFrame(raf.current);
    setHold((h) => (h >= 1 ? h : 0));
  };

  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  return (
    <div className="rise flex flex-1 flex-col gap-3 p-5">
      <div className="text-[14px] text-[var(--mu)]">{t.sensitive}</div>
      <div className="rounded-xl border border-[var(--line)] bg-[rgba(2,10,20,.55)] p-3">
        <div className="font-medium">{g.title[lang]}</div>
        <div className="mt-2 flex items-center gap-2 text-[14px]">
          <span className="text-[var(--mu)]">{t.requestedBy}</span>
          <span className="mono text-[var(--sun2)]">{g.by}</span>
        </div>
        <div className="mt-1 flex items-center gap-2 text-[14px]">
          <span className="text-[var(--mu)]">{t.target}</span>
          <span className="mono break-all text-[var(--sun2)]">{g.target}</span>
        </div>
      </div>
      <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[rgba(1,6,12,.85)]" dir="ltr">
        <div className="flex items-center gap-2 border-b border-[var(--line)] px-3 py-2 text-[14px]">
          <span>{t.diff}</span>
          <EyeOff size={14} className="ms-auto text-[var(--mu)]" />
        </div>
        <div className="mono scroll overflow-x-auto py-2 text-[13px] leading-[1.8]">
          {g.diff.map((row, i) => {
            const sign = row[0] === "s" ? "-" : row[0];
            const bg = sign === "+" ? "rgba(95,240,168,.1)" : sign === "-" ? "rgba(255,92,122,.1)" : "transparent";
            const bar = sign === "+" ? "#5ff0a8" : sign === "-" ? "#ff5c7a" : "transparent";
            const fg = sign === "+" ? "#c4f7dc" : sign === "-" ? "#ffc0ca" : "#a9c6d6";
            return (
              <div key={i} className="flex whitespace-pre-wrap break-all pe-3" style={{ background: bg, boxShadow: `inset 2px 0 0 ${bar}` }}>
                <span className="w-7 shrink-0 select-none text-center" style={{ color: bar === "transparent" ? "#3d5a6e" : bar }}>
                  {sign === " " ? "" : sign}
                </span>
                {row[0] === "s" ? (
                  <span style={{ color: fg }}>
                    {row[1]}
                    <span className="rounded bg-[#0d2433] px-1 tracking-[.2em] text-[#6f8ea3]">••••••</span>
                    {row[3]}
                    <span className="ms-2 rounded border border-[rgba(255,154,82,.4)] px-1.5 text-[12px] text-[var(--await)]">
                      {t.redacted}
                      {" "}
                      {row[2]}
                    </span>
                  </span>
                ) : (
                  <span style={{ color: fg }}>{row[1]}</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex gap-3 rounded-xl border border-[rgba(255,154,82,.4)] bg-[rgba(255,154,82,.08)] p-3">
        <TriangleAlert size={20} className="shrink-0 text-[var(--await)]" />
        <div>
          <div className="font-medium text-[var(--await)]">
            {t.warnTitle}
            {" "}
            {g.tier}
          </div>
          <div className="text-[14px] text-[#e2cdb8]">{t.warnBody}</div>
        </div>
      </div>
      <div className="mt-auto flex items-center gap-2.5 text-[14px]">
        <span className="text-[var(--mu)]">{t.approver}</span>
        <span>{APPROVER.name}</span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {g.tier === 3 ? (
          <button
            onPointerDown={begin}
            onPointerUp={end}
            onPointerLeave={end}
            aria-label="Hold to approve"
            className="relative touch-none select-none overflow-hidden whitespace-nowrap rounded-full border border-[rgba(56,232,255,.6)] px-2 py-3 text-[14px] font-semibold text-[#e6fdff]"
            style={{ boxShadow: "0 0 24px -6px rgba(56,232,255,.5)" }}
          >
            <span className="absolute inset-y-0 bg-[linear-gradient(90deg,#1fc6e6,#9af7ff)] ltr:left-0 rtl:right-0" style={{ width: `${hold * 100}%` }} />
            <span className="relative flex items-center justify-center gap-2" style={{ color: hold > 0.5 ? "#00222c" : undefined }}>
              <Check size={17} />
              {t.hold}
            </span>
          </button>
        ) : (
          <button
            onClick={() => decide(true)}
            aria-label="Approve"
            className="btn-core flex items-center justify-center gap-2 rounded-full px-3 py-3 font-semibold transition hover:brightness-110"
          >
            <Check size={17} />
            {t.approve}
          </button>
        )}
        <button
          onClick={() => decide(false)}
          aria-label="Reject"
          className="flex items-center justify-center gap-2 rounded-full border border-[rgba(255,92,122,.5)] bg-[rgba(255,92,122,.1)] px-3 py-3 font-semibold text-[#ffc0ca] transition hover:bg-[rgba(255,92,122,.18)]"
        >
          <X size={17} />
          {t.reject}
        </button>
      </div>
    </div>
  );
}
