// Timeline (skill 06): one row per run, nested by parent.
// Interval bars show active, waiting and terminal segments.
// Selection syncs with the canvas and the Inspector.
// Replay is observational only — it never triggers
// tools or config changes.
import { useEffect, useMemo, useRef } from "react";
import { Pause, Play } from "lucide-react";
import { RUN_STATE_COLOR } from "../scene/colors.js";
import {
  runInterval,
  waitingSegments,
  elapsedMs,
  isRunActive,
  runsInOrder,
  depthOfRun,
  missionList,
} from "../model/runtime.js";

function formatElapsed(ms) {
  if (ms == null) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2, "0")}s`;
}

function timeLabel(ms) {
  if (ms == null) return "—";
  const d = new Date(ms);
  return [d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
}

export default function Timeline({
  t,
  lang,
  rtl,
  store,
  agents,
  selectedRun,
  onSelectRun,
  cursor,
  setCursor,
  playing,
  setPlaying,
  missionFilter,
  setMissionFilter,
  activeOnly,
  setActiveOnly,
  replayEvents,
}) {
  const listRef = useRef();

  // Keep the selected run row in view.
  useEffect(() => {
    if (selectedRun == null) return;
    listRef.current
      ?.querySelector(`[data-run="${selectedRun}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, [selectedRun]);

  const missions = useMemo(() => missionList(store), [store]);

  // Rows: filtered, ordered, nested by parent.
  const rows = useMemo(
    () =>
      runsInOrder(store)
        .map((run) => ({ run, depth: depthOfRun(store, run.runId) }))
        .filter(({ run }) => missionFilter === "all" || run.missionId === missionFilter)
        .filter(({ run }) => !activeOnly || isRunActive(run)),
    [store, missionFilter, activeOnly]
  );

  // Time domain for the interval bars.
  const domain = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const { run } of rows) {
      const iv = runInterval(run);
      if (iv?.start != null) min = Math.min(min, iv.start);
      if (iv?.end != null) max = Math.max(max, iv.end);
    }
    return min === Infinity ? [0, 1] : [min, Math.max(max, min + 1)];
  }, [rows]);

  const pct = (ms) =>
    `${Math.max(0, Math.min(100, ((ms - domain[0]) / (domain[1] - domain[0])) * 100))}%`;

  const agentName = (id) => agents.find((a) => a.id === id)?.name || id;

  // Scrubber dots: one per run start (event dots would
  // overlap at this density).
  const runStartDots = useMemo(
    () =>
      replayEvents
        .map((ev, i) => ({ ev, i }))
        .filter(({ ev }) => ev.type === "run.created"),
    [replayEvents]
  );

  const pctCursor =
    cursor === null ? 100 : (cursor / Math.max(1, replayEvents.length - 1)) * 100;

  return (
    <section className="glass p-4 lg:col-span-2">
      <div className="flex flex-wrap items-center gap-3 px-1">
        <h2 className="disp text-[22px] leading-none">{t.timeline}</h2>
        <span className="mock-tag">MOCK</span>
        <span className="flex items-center gap-2 text-[14px] text-[var(--sun)]">
          <i className="dotlive h-2 w-2 rounded-full bg-[var(--sun)] text-[var(--sun)]" />
          {t.live}
        </span>
        <div className="ms-auto flex items-center gap-2">
          <select
            value={missionFilter}
            onChange={(e) => setMissionFilter(e.target.value)}
            aria-label={t.missionFilter}
            className="rounded-full border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-1.5 text-[13px]"
          >
            <option value="all">{t.allMissions}</option>
            {missions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setActiveOnly(!activeOnly)}
            aria-pressed={activeOnly}
            className={`chip ${activeOnly ? "!border-[var(--sun)] !text-[var(--sun)]" : ""}`}
          >
            {t.activeOnly}
          </button>
        </div>
      </div>

      <div
        ref={listRef}
        className="scroll mt-3 flex max-h-[280px] flex-col gap-1.5 overflow-y-auto pb-1"
      >
        {rows.length === 0 && (
          <div className="px-2 py-3 text-[13px] text-[var(--mu)]">{t.noRuns}</div>
        )}
        {rows.map(({ run, depth }) => {
          const iv = runInterval(run);
          const waits = waitingSegments(run);
          const on = selectedRun === run.runId;
          const col = RUN_STATE_COLOR[run.state] || "#6b7fa6";
          return (
            <button
              key={run.runId}
              data-run={run.runId}
              onClick={() => onSelectRun(on ? null : run.runId)}
              className="rise rounded-xl border bg-[rgba(2,10,20,.6)] p-2.5 text-start transition"
              style={{
                marginInlineStart: depth * 22,
                borderColor: on ? col : `${col}44`,
                boxShadow: on ? `0 0 18px -4px ${col}` : undefined,
              }}
            >
              <div className="flex items-center gap-2">
                <i
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: col, boxShadow: `0 0 6px ${col}` }}
                />
                <span className="text-[13px] font-medium">{agentName(run.agentId)}</span>
                <span className="mono truncate text-[11px] text-[var(--mu)]">
                  {run.runId}
                </span>
                <span className="ms-auto shrink-0 text-[12px]" style={{ color: col }}>
                  {t.runStates[run.state]}
                  {run.state === "waiting" && run.waitingReason
                    ? ` · ${t.waitingReasons[run.waitingReason]}`
                    : ""}
                </span>
                <span className="mono shrink-0 text-[11px] text-[var(--mu)]">
                  {formatElapsed(elapsedMs(run))}
                </span>
              </div>
              {run.assignedTask && (
                <div className="mt-1 truncate text-[12px] text-[var(--mu)]">
                  {run.assignedTask}
                </div>
              )}
              {/* interval bar: active + waiting + terminal marker */}
              <div className="relative mt-1.5 h-1.5 rounded bg-[#0b2233]" dir="ltr">
                {iv?.start != null && iv.end != null && (
                  <div
                    className="absolute h-full rounded"
                    style={{
                      left: pct(iv.start),
                      width: `calc(${pct(iv.end)} - ${pct(iv.start)})`,
                      background: `linear-gradient(90deg, ${col}88, ${col})`,
                      opacity: isRunActive(run) ? 0.9 : 0.55,
                    }}
                  />
                )}
                {waits.map(
                  (w, i) =>
                    w.from != null &&
                    w.to != null && (
                      <div
                        key={i}
                        className="absolute h-full rounded"
                        style={{
                          left: pct(w.from),
                          width: `calc(${pct(w.to)} - ${pct(w.from)})`,
                          background:
                            "repeating-linear-gradient(45deg, #ffd16688, #ffd16688 3px, transparent 3px, transparent 6px)",
                        }}
                      />
                    )
                )}
                {run.endedAt != null && (
                  <div
                    className="absolute top-1/2 h-2.5 w-[2px] -translate-y-1/2"
                    style={{ left: pct(run.endedAt), background: col }}
                  />
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* replay scrubber — observational only */}
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
            style={{ width: `${pctCursor}%`, boxShadow: "0 0 10px #38e8ff88" }}
          />
          {runStartDots.map(({ ev, i }) => (
            <button
              key={ev.eventId}
              onClick={() => setCursor(i)}
              aria-label={timeLabel(ev.occurredAt)}
              className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
            >
              <span
                className="mx-auto block h-2.5 w-[2px] rounded"
                style={{ background: i === cursor ? "#38e8ff" : "#2c4a5e" }}
              />
            </button>
          ))}
          <div
            className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--sun)] bg-[#03121c] transition-all duration-500"
            style={{ left: `${pctCursor}%`, boxShadow: "0 0 12px #38e8ff" }}
          />
        </div>
        <span className="mono w-12 text-[13px] text-[var(--mu)]">
          {cursor === null ? "LIVE" : timeLabel(replayEvents[cursor]?.occurredAt)}
        </span>
      </div>
    </section>
  );
}
