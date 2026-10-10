// Minified name in bundle: mx.
import { useState } from "react";
import { Trash2, X, Cable, Database } from "lucide-react";
import { STATUS_COLOR, SUN, RUN_STATE_COLOR } from "../scene/colors.js";

export default function StatusCard({ a, t, rtl, lang, mode, onConnect, onClose, onRemove, memory, run, freshness }) {
  const col = a.id === "hermes" ? SUN : STATUS_COLOR[a.status];
  // Skill 05: selected scope for memory retrieval (UI-only state).
  const [scope, setScope] = useState(null);
  const activeScope = scope || (memory && memory.scopes[0]);
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
        {mode === "edit" && (
          <button
            type="button"
            onClick={onConnect}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-full border border-[rgba(56,232,255,.45)] py-2 text-[14px] text-[#e6fdff] transition hover:bg-[rgba(56,232,255,.12)]"
          >
            <Cable size={14} />
            {t.connectTo}
          </button>
        )}
        {memory && (
          <div className="mt-3 border-t border-[var(--line)] pt-3">
            <div className="text-[12px] text-[var(--mu)]">
              {t.memoryRetrieve}
            </div>
            {/* Phase 0 fix (audit ISS-02): capability first — if the provider
                declares queryMemory unsupported, say so with an explanation
                (skill 08) instead of offering a Retrieve action that only
                produces an error. */}
            {memory.supported === false ? (
              <div className="mt-2 text-[12px] text-[#ffd166]">
                ⚠ {t.memoryUnsupported}
              </div>
            ) : !memory.connected ? (
              <div className="mt-2 text-[12px] text-[#ffd166]">
                ⚠ {t.memoryNotConnected}
              </div>
            ) : (
              <>
                <select
                  value={activeScope}
                  onChange={(e) => setScope(e.target.value)}
                  className="mt-2 w-full rounded-full border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-1.5 text-[13px]"
                  aria-label={t.memoryScope}
                >
                  {memory.scopes.map((s) => (
                    <option key={s} value={s}>
                      {s} —{" "}
                      {memory.granted.includes(s)
                        ? t.memoryGranted
                        : t.memoryNoGrant}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => activeScope && memory.onRetrieve(activeScope)}
                  disabled={memory.retrieving || !activeScope}
                  className="chip mt-2 w-full justify-center disabled:opacity-40"
                >
                  <Database size={13} />
                  {memory.retrieving ? t.applying : t.memoryRetrieveBtn}
                </button>
                {memory.result && (
                  <div className="mt-2">
                    {memory.result.status === "allowed" ? (
                      memory.result.items.length > 0 ? (
                        <ul className="flex flex-col gap-1">
                          {memory.result.items.map((item) => (
                            <li
                              key={item.id}
                              className="rounded border border-[rgba(95,240,168,.3)] bg-[rgba(95,240,168,.06)] px-2 py-1.5 text-[12px]"
                            >
                              <div className="flex items-center gap-1.5">
                                <span className="mock-tag">MOCK</span>
                                <span className="font-semibold text-[#c4f7dc]">
                                  {item.title}
                                </span>
                              </div>
                              <div className="mono mt-0.5 text-[11px] text-[var(--mu)]">
                                {item.source}
                              </div>
                              {item.tags.length > 0 && (
                                <div className="mt-0.5 text-[11px] text-[var(--mu)]">
                                  {item.tags.join(" · ")}
                                </div>
                              )}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <div className="text-[12px] text-[var(--mu)]">
                          {t.memoryNoItems}
                        </div>
                      )
                    ) : (
                      <div className="rounded border border-[rgba(255,92,122,.4)] bg-[rgba(255,92,122,.08)] px-2 py-1.5 text-[12px] text-[#ffc0ca]">
                        {memory.result.status === "denied" ? "⛔ " : "⚠ "}
                        {memory.result.error}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
        {run && (
          <div className="mt-3 border-t border-[var(--line)] pt-3">
            <div className="flex items-center gap-2">
              <span className="text-[12px] font-semibold text-[var(--sun2)]">
                {t.run}
              </span>
              <span className="mono text-[11px] text-[var(--mu)]">{run.runId}</span>
              <span
                className="ms-auto text-[12px]"
                style={{ color: RUN_STATE_COLOR[run.state] || "#6b7fa6" }}
              >
                {t.runStates[run.state]}
              </span>
            </div>
            <dl className="mt-1.5 flex flex-col gap-1 text-[12px] text-[var(--mu)]">
              <div className="flex gap-2">
                <dt>{t.mission}</dt>
                <dd className="mono text-[var(--tx)]">{run.missionId || "—"}</dd>
              </div>
              {run.parentRunId && (
                <div className="flex gap-2">
                  <dt>{t.parentRun}</dt>
                  <dd className="mono text-[var(--tx)]">{run.parentRunId}</dd>
                </div>
              )}
              {run.assignedTask && (
                <div className="flex gap-2">
                  <dt>{t.task}</dt>
                  <dd className="text-[var(--tx)]">{run.assignedTask}</dd>
                </div>
              )}
              {run.state === "waiting" && run.waitingReason && (
                <div className="flex gap-2">
                  <dt>{t.waitingFor}</dt>
                  <dd className="text-[#ffd166]">
                    {t.waitingReasons[run.waitingReason]}
                  </dd>
                </div>
              )}
              {run.error && (
                <div className="flex gap-2">
                  <dt>{t.error}</dt>
                  <dd className="text-[#ffc0ca]">{run.error}</dd>
                </div>
              )}
              {run.activity.length > 0 && (
                <div className="flex gap-2">
                  <dt>{t.lastActivity}</dt>
                  <dd className="text-[var(--tx)]">
                    {run.activity[run.activity.length - 1].text}
                  </dd>
                </div>
              )}
              {run.artifacts.length > 0 && (
                <div className="flex gap-2">
                  <dt>{t.artifacts}</dt>
                  <dd className="mono text-[var(--tx)]">
                    {run.artifacts.join(", ")}
                  </dd>
                </div>
              )}
            </dl>
          </div>
        )}
        <div className="mt-3 border-t border-[var(--line)] pt-2 text-[12px] text-[var(--mu)]">
          {freshness === "unavailable" ? (
            <span className="text-[#ffd166]">ⓘ {t.telemetryUnavailable}</span>
          ) : (
            <span>
              {t.subagentTelemetry}:{" "}
              <span style={{ color: freshness === "stale" ? "#ffd166" : "#5ff0a8" }}>
                {t.freshness[freshness]}
              </span>
            </span>
          )}
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
