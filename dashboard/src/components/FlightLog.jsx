// Minified name in bundle: Lx.
import { useEffect, useRef } from "react";
import { Activity, Box, CodeXml, Database, Pause, Play, Plus, Rocket, ShieldCheck, Trash2 } from "lucide-react";
import { STATUS_COLOR, SUN } from "../scene/colors.js";

// dx
const EVENT_ICONS = { add: Plus, remove: Trash2, code: CodeXml, box: Box, db: Database, gate: ShieldCheck, rocket: Rocket, pulse: Activity };

// bc
export const evColor = (ev, agents) =>
  ev.c || (ev.bad ? "#ff5c7a" : ev.agent === "hermes" ? SUN : STATUS_COLOR[agents.find((a) => a.id === ev.agent)?.status || "running"]);

export default function FlightLog({ t, lang, history, agents, cursor, setCursor, playing, setPlaying, dataSource }) {
  const listRef = useRef();

  useEffect(() => {
    cursor !== null && listRef.current?.children[cursor]?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [cursor]);

  const pct = cursor === null ? 100 : (cursor / Math.max(1, history.length - 1)) * 100;

  return (
    <section className="glass p-4 lg:col-span-2">
      <div className="flex items-center gap-3 px-1">
        <h2 className="disp text-[22px] leading-none">{t.history}</h2>
        {dataSource === "demo" && <span className="rounded border border-[var(--await)] bg-[rgba(255,154,82,.1)] px-1.5 py-0.5 text-[10px] text-[var(--await)] tracking-widest">{t.demoData || "Demo"}</span>}
        <span className="ms-auto flex items-center gap-2 text-[14px] text-[var(--sun)]">
          <i className="dotlive h-2 w-2 rounded-full bg-[var(--sun)] text-[var(--sun)]" />
          {t.live}
        </span>
      </div>
      <div ref={listRef} className="scroll mt-3 flex gap-3 overflow-x-auto pb-2">
        {history.map((ev, i) => {
          const Icon = EVENT_ICONS[ev.kind];
          const col = evColor(ev, agents);
          const on = cursor === i;
          return (
            <button
              key={i}
              onClick={() => setCursor(on ? null : i)}
              className="rise min-w-[180px] shrink-0 rounded-xl border bg-[rgba(2,10,20,.6)] p-3 text-start transition"
              style={{
                borderColor: on ? col : `${col}44`,
                boxShadow: on ? `0 0 22px -4px ${col}, inset 0 0 18px -10px ${col}` : `inset 0 0 14px -10px ${col}`,
              }}
            >
              <div className="flex items-center gap-2">
                <span className="grid h-7 w-7 place-items-center rounded-full" style={{ background: `${col}22`, color: col }}>
                  <Icon size={15} />
                </span>
                <span className="text-[14px] font-medium">{ev.ev[lang]}</span>
              </div>
              <div className="mono mt-2 text-[13px] text-[#c9e3ee]">{ev.ref}</div>
              <div className="mt-1 flex items-center justify-between text-[13px] text-[var(--mu)]">
                <span className="mono">{ev.t}</span>
                <i className="h-2 w-2 rounded-full" style={{ background: col, boxShadow: `0 0 6px ${col}` }} />
              </div>
            </button>
          );
        })}
      </div>
      <div className="mt-3 flex items-center gap-3 px-1" dir="ltr">
        <button
          onClick={() => {
            !playing && cursor === null && setCursor(0);
            setPlaying(!playing);
          }}
          aria-label={t.replay}
          className="grid h-9 w-9 place-items-center rounded-full border border-[var(--line)] text-[var(--sun)] hover:bg-[rgba(56,232,255,.08)]"
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <div className="relative h-8 flex-1">
          <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded bg-[#0b2233]" />
          <div
            className="absolute left-0 top-1/2 h-1 -translate-y-1/2 rounded bg-[linear-gradient(90deg,#c77dff,#38e8ff)] transition-all duration-500"
            style={{ width: `${pct}%`, boxShadow: "0 0 10px #38e8ff88" }}
          />
          {history.map((ev, i) => (
            <button
              key={i}
              onClick={() => setCursor(i)}
              aria-label={ev.t}
              className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{ left: `${(i / Math.max(1, history.length - 1)) * 100}%` }}
            >
              <span className="mx-auto block h-3 w-[2px] rounded" style={{ background: i === cursor ? evColor(ev, agents) : "#2c4a5e" }} />
            </button>
          ))}
          <div
            className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--sun)] bg-[#03121c] transition-all duration-500"
            style={{ left: `${pct}%`, boxShadow: "0 0 12px #38e8ff" }}
          />
        </div>
        <span className="mono w-12 text-[13px] text-[var(--mu)]">{cursor === null ? "LIVE" : history[cursor].t}</span>
      </div>
    </section>
  );
}
