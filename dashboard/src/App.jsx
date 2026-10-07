// Minified name in bundle: Fs.
import { useEffect, useMemo, useState } from "react";
import { Brain, Cable, Check, Crosshair, Search, SlidersHorizontal, X } from "lucide-react";
import { AGENTS, APPROVALS, HISTORY, LINKS, T, DATA_SOURCE } from "./data.js";
import { STATUS_COLOR, SUN } from "./scene/colors.js";
import NeuralScene from "./scene/NeuralScene.jsx";
import Header from "./components/Header.jsx";
import { useConnection } from "./connection/ConnectionProvider.jsx";
import Sidebar from "./components/Sidebar.jsx";
import StatusCard from "./components/StatusCard.jsx";
import Gate from "./components/Gate.jsx";
import FlightLog from "./components/FlightLog.jsx";
import AddTool from "./components/AddTool.jsx";
import Btn from "./components/Btn.jsx";

const STORAGE_KEY = "agentos-neural-tools-v1";

const loadCustom = () => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  } catch {
    return [];
  }
};

const saveCustom = (list) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {}
};

const hhmm = () => {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

export default function App() {
  const { state: connState } = useConnection();
  const [lang, setLang] = useState("fa");
  const t = T[lang];
  const rtl = lang === "fa";

  const [agents, setAgents] = useState(() => [...AGENTS, ...loadCustom()]);
  const [adding, setAdding] = useState(false);
  const links = useMemo(
    () => [...LINKS, ...agents.filter((a) => a.custom).map((a) => ({ from: a.parent || "hermes", to: a.id }))],
    [agents]
  );

  useEffect(() => {
    saveCustom(agents.filter((a) => a.custom));
  }, [agents]);

  const [approvals, setApprovals] = useState(APPROVALS);
  const [history, setHistory] = useState(HISTORY);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [toast, setToast] = useState(null);
  const [burst, setBurst] = useState(null);

  const fire = (id) => setBurst({ id, n: Math.random() });
  const flash = (ok, id, msg) => {
    setToast({ ok, id, msg });
    setTimeout(() => setToast(null), 2600);
  };

  // flight-log replay
  useEffect(() => {
    if (!playing) return;
    const iv = setInterval(
      () =>
        setCursor((c) => {
          const next = c === null ? 0 : c + 1;
          return next >= history.length ? (setPlaying(false), null) : next;
        }),
      1300
    );
    return () => clearInterval(iv);
  }, [playing, history.length]);

  const replayAgent = cursor !== null ? history[cursor]?.agent : null;
  useEffect(() => {
    replayAgent && fire(replayAgent);
  }, [cursor]);

  const focusId = selected || replayAgent;
  const focused = agents.find((a) => a.id === focusId);

  const addTool = (a) => {
    setAgents((list) => [...list, a]);
    setHistory((h) => [...h, { t: hhmm(), kind: "add", agent: a.id, c: SUN, ev: { en: T.en.evAdd, fa: T.fa.evAdd }, ref: a.name }]);
    setAdding(false);
    setSelected(a.id);
    flash(true, a.name, t.launched);
    setTimeout(() => fire(a.id), 200);
  };

  const removeTool = (id) => {
    const a = agents.find((x) => x.id === id);
    setAgents((list) => list.filter((x) => x.id !== id && x.parent !== id));
    setHistory((h) => [...h, { t: hhmm(), kind: "remove", agent: "hermes", c: "#ff5c7a", ev: { en: T.en.evRemove, fa: T.fa.evRemove }, ref: a?.name }]);
    setSelected(null);
    flash(false, a?.name, t.removed);
  };

  const decide = (g, ok) => {
    setAgents((list) =>
      list.map((a) => (a.id === g.agent ? { ...a, status: ok ? (g.agent === "wordpress" ? "complete" : "running") : "offline" } : a))
    );
    setApprovals((q) => q.filter((x) => x.id !== g.id));
    setHistory((h) => [
      ...h,
      {
        t: hhmm(),
        kind: "gate",
        agent: g.agent,
        c: ok ? "#5ff0a8" : "#ff5c7a",
        ev: ok ? { en: `${g.id} approved`, fa: `${g.id} تأیید شد` } : { en: `${g.id} rejected`, fa: `${g.id} رد شد` },
        ref: g.by,
      },
    ]);
    flash(ok, g.id);
    ok && fire(g.agent);
  };

  const counts = useMemo(() => {
    const c = { running: 0, awaiting: 0, complete: 0, offline: 0 };
    agents.forEach((a) => c[a.status]++);
    return c;
  }, [agents]);

  const labelFor = (a) => (
    <div className={rtl ? "f-fa" : "f-en"}>
      <b>{a.name}</b>
      <small>{a.sub[lang]}</small>
      <span className="st" style={{ color: STATUS_COLOR[a.status] }}>
        <i style={{ background: STATUS_COLOR[a.status] }} />
        {t.legend[a.status]}
      </span>
    </div>
  );

  const coreLabel = (
    <span className={rtl ? "f-fa" : "f-en"}>
      <Brain size={16} />
      <em>Hermes</em>
      {"· "}
      {t.brain}
    </span>
  );

  return (
    <div dir={rtl ? "rtl" : "ltr"} className={`deck text-[15px] ${rtl ? "f-fa" : "f-en"}`}>
      <Header t={t} lang={lang} setLang={setLang} />
      <div className="grid grid-cols-1 gap-4 p-4 [&>*]:min-w-0 lg:grid-cols-[210px_1fr_370px] lg:grid-rows-[minmax(700px,1fr)_auto]">
                <Sidebar t={t} />

        <section className="glass hud-frame relative flex min-h-[700px] flex-col overflow-hidden">
          <div className="relative z-10 flex flex-wrap items-end gap-x-4 gap-y-1 px-6 pt-5">
            <h2 className="disp text-[32px] leading-none text-[var(--sun2)]" style={{ textShadow: "0 0 18px rgba(56,232,255,.45)" }}>
              {t.graph}
            </h2>
                        <span className="pb-0.5 text-[15px] text-[var(--mu)]">{t.graphSub}</span>
            {DATA_SOURCE === "demo" && <span className="ms-2 rounded border border-[var(--await)] bg-[rgba(255,154,82,.1)] px-2 py-0.5 text-[11px] text-[var(--await)] tracking-widest uppercase">{t.demoData || "Demo data"}</span>}
            <span className="mono ms-auto pb-0.5 text-[14px] text-[var(--mu)]">wp-bioscentiran</span>
          </div>
          <div className="relative z-10 flex flex-wrap gap-2 px-6 pt-4">
            <label className="flex min-w-[220px] flex-1 items-center gap-2 rounded-full border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-4 py-2">
              <Search size={16} className="text-[var(--mu)]" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t.search}
                className="w-full bg-transparent text-[15px] outline-none"
              />
            </label>
            <button
              onClick={() => setAdding(true)}
              className="btn-core flex items-center gap-2 rounded-full px-4 py-2 text-[14px] font-semibold transition hover:brightness-110"
            >
              <Cable size={16} />
              {t.add}
            </button>
            <Btn icon={SlidersHorizontal}>{t.filter}</Btn>
            <Btn
              icon={Crosshair}
              onClick={() => {
                setQuery("");
                setSelected(null);
                setCursor(null);
              }}
            >
              {t.refresh}
            </Btn>
          </div>
          <div className="relative mt-2 min-h-[500px] flex-1" dir="ltr">
            <NeuralScene
              agents={agents}
              links={links}
              selected={selected}
              setSelected={setSelected}
              highlight={replayAgent}
              query={query}
              labelFor={labelFor}
              coreLabel={coreLabel}
              burst={burst}
              rtl={rtl}
            />
            {focused && (
              <StatusCard
                key={focused.id}
                a={focused}
                t={t}
                rtl={rtl}
                lang={lang}
                onClose={() => {
                  setSelected(null);
                  setCursor(null);
                }}
                onRemove={focused.custom ? () => removeTool(focused.id) : null}
              />
            )}
            {adding && <AddTool t={t} rtl={rtl} agents={agents} onCancel={() => setAdding(false)} onAdd={addTool} />}
          </div>
          <div className="relative z-10 flex flex-wrap items-stretch gap-3 px-5 pb-4">
            <div className="glass px-4 py-3">
              <div className="text-[14px] text-[var(--mu)]">{t.statusTitle}</div>
              <div className="mt-1.5 flex items-center gap-3">
                {Object.keys(counts).map((s) => (
                  <span key={s} className="flex items-center gap-1.5" title={t.legend[s]}>
                    <i className="h-2.5 w-2.5 rounded-full" style={{ background: STATUS_COLOR[s], boxShadow: `0 0 8px ${STATUS_COLOR[s]}` }} />
                    <span className="mono text-[14px]">{counts[s]}</span>
                  </span>
                ))}
              </div>
            </div>
            <div className="glass px-4 py-3">
              <div className="text-[14px] text-[var(--mu)]">{t.lastRun}</div>
              <div className="mt-1.5 flex items-center gap-2">
                <i className="h-2 w-2 rounded-full bg-[var(--sun)]" style={{ boxShadow: "0 0 8px #38e8ff" }} />
                <span className="mono text-[14px]">wp-bioscentiran · 17:46:02</span>
              </div>
            </div>
            <div className="ms-auto flex flex-wrap items-center gap-x-4 gap-y-1 self-end pb-1 text-[14px] text-[var(--mu)]">
              {Object.keys(t.legend).map((s) => (
                <span key={s} className="flex items-center gap-2">
                  <i className="h-[3px] w-5 rounded-full" style={{ background: STATUS_COLOR[s], boxShadow: `0 0 8px ${STATUS_COLOR[s]}` }} />
                  {t.legend[s]}
                </span>
              ))}
            </div>
          </div>
        </section>
        <Gate approvals={approvals} t={t} lang={lang} decide={decide} dataSource={DATA_SOURCE} />
        <FlightLog dataSource={DATA_SOURCE} t={t} lang={lang} history={history}
          agents={agents}
          cursor={cursor}
          setCursor={(c) => {
            setCursor(c);
            setSelected(null);
          }}
          playing={playing}
          setPlaying={setPlaying}
        />
      </div>
      {toast && (
        <div
          className="rise glass fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 px-4 py-2.5"
          style={{ borderColor: toast.ok ? "rgba(95,240,168,.5)" : "rgba(255,92,122,.5)" }}
        >
          {toast.ok ? <Check size={16} color="#5ff0a8" /> : <X size={16} color="#ff5c7a" />}
          <span className="mono text-[14px]">{toast.id}</span>
          <span>{toast.msg || (toast.ok ? t.approved : t.rejected)}</span>
        </div>
      )}
    </div>
  );
}
