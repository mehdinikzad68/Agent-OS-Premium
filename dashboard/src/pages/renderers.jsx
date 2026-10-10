// Standard page renderers (skill 07). The manifest only ever
// carries a renderer NAME; this registry maps names to plain
// components. No page fetches data, evals anything, or mutates
// configuration — everything is rendered from the validated
// workspace context (MOCK/demo data, labeled by the router).

import { RUN_STATE_COLOR, STATUS_COLOR } from "../scene/colors.js";
import { elapsedMs, runsInOrder, subagentFreshness } from "../model/runtime.js";

const FRESHNESS_COLOR = {
  fresh: "#5ff0a8",
  stale: "#ffd166",
  unavailable: "#8a97a5",
};

const secs = (ms) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)}s`);

const label = (loc, lang, fallback) =>
  (loc && (loc[lang] || loc.en)) || fallback || "";

/** Build the table model for a declarative source id.
 *  Returns { head, rows: [{ key, cells, tone? }] } or null for
 *  unknown sources — the caller shows a readable note instead. */
function tableFor(source, t, lang, ctx) {
  const kinds = ctx.kinds || {};
  switch (source) {
    case "agents":
      return {
        head: [t.colName, t.colKind, t.colStatus],
        rows: ctx.agents.map((a) => ({
          key: a.id,
          cells: [a.name, kinds[a.id] || "tool", t.legend[a.status] || a.status],
          tone: STATUS_COLOR[a.status],
        })),
      };
    case "tools":
      return {
        head: [t.colName, t.role, t.colStatus],
        rows: ctx.agents
          .filter((a) => kinds[a.id] === "tool")
          .map((a) => ({
            key: a.id,
            cells: [a.name, a.sub ? a.sub[lang] : "—", t.legend[a.status] || a.status],
            tone: STATUS_COLOR[a.status],
          })),
      };
    case "models":
      return {
        head: [t.colName, t.colProvider, t.colState],
        rows: (ctx.models || []).map((m) => ({
          key: m.id,
          cells: [m.name, m.provider, m.state],
          tone: m.state === "active" ? STATUS_COLOR.running : STATUS_COLOR.offline,
        })),
      };
    case "connections":
      return {
        head: [t.colFrom, t.colTo, t.colType, t.colState],
        rows: ctx.connections.map((c) => ({
          key: c.id,
          cells: [
            c.from,
            c.to,
            (t.types && t.types[c.type]) || c.type,
            t[c.state] || c.state,
          ],
          tone: c.state === "disabled" ? STATUS_COLOR.offline : STATUS_COLOR.running,
        })),
      };
    case "pages":
      return {
        head: [t.colTitle, t.colRoute, t.colRenderer],
        rows: ctx.pages.map((p) => ({
          key: p.id,
          cells: [label(p.title, lang, p.id), p.route, p.renderer],
        })),
      };
    case "freshness":
      return {
        head: [t.colName, t.subagentTelemetry],
        rows: ctx.agents.map((a) => {
          const level = subagentFreshness(ctx.runtime, a.id);
          return {
            key: a.id,
            cells: [a.name, t.freshness[level] || level],
            tone: FRESHNESS_COLOR[level] || FRESHNESS_COLOR.unavailable,
          };
        }),
      };
    case "runs":
      return {
        head: [t.run, t.colAgent, t.colState, t.mission, t.colElapsed],
        rows: runsInOrder(ctx.runtime).map((r) => ({
          key: r.runId,
          cells: [
            r.runId,
            r.agentId,
            t.runStates[r.state] || r.state,
            r.missionId || "—",
            secs(elapsedMs(r)),
          ],
          tone: RUN_STATE_COLOR[r.state],
        })),
      };
    default:
      return null;
  }
}

function Note({ children }) {
  return (
    <div className="glass max-w-[560px] p-4 text-[14px] text-[var(--mu)]">
      {children}
    </div>
  );
}

/** resource-table — a declarative data table. */
export function ResourceTablePage({ page, t, lang, ctx }) {
  const source = page.props && page.props.source;
  const table = tableFor(source, t, lang, ctx);
  if (!table) {
    return (
      <Note>
        {t.unknownSource}: <span className="mono">{String(source ?? "—")}</span>
      </Note>
    );
  }
  if (table.rows.length === 0) {
    return <Note>{t.emptyTable}</Note>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-start text-[14px]">
        <thead>
          <tr className="border-b border-[var(--line)] text-[13px] text-[var(--mu)]">
            {table.head.map((h, i) => (
              <th key={`h-${i}`} className="px-3 py-2 text-start font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r) => (
            <tr key={r.key} className="border-b border-[rgba(56,232,255,.08)]">
              {r.cells.map((c, i) => (
                <td
                  key={`c-${i}`}
                  className="px-3 py-2"
                  style={i === 0 && r.tone ? { color: r.tone } : undefined}
                >
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** resource-detail — one entity, read-only. */
export function ResourceDetailPage({ page, t, lang, ctx }) {
  const props = page.props || {};
  const id = props.id;
  const agent = ctx.agents.find((a) => a.id === id);
  if (!agent) {
    return (
      <Note>
        {t.itemNotFound}: <span className="mono">{String(id ?? "—")}</span>
      </Note>
    );
  }
  const linkCount = ctx.connections.filter(
    (c) => c.from === agent.id || c.to === agent.id
  ).length;
  const rows = [
    [t.colName, agent.name],
    [t.role, (agent.sub && (agent.sub[lang] || agent.sub.en)) || "—"],
    [t.colKind, ctx.kinds[agent.id] || "tool"],
    [t.colStatus, t.legend[agent.status] || agent.status],
    [t.colConnections, String(linkCount)],
  ];
  return (
    <div className="glass max-w-[560px] p-5">
      <div className="flex items-center gap-3">
        <b className="text-[18px]">{agent.name}</b>
        <span
          className="mono rounded-full px-2 py-0.5 text-[12px]"
          style={{
            color: STATUS_COLOR[agent.status],
            background: "rgba(2,10,20,.6)",
            border: `1px solid ${STATUS_COLOR[agent.status]}55`,
          }}
        >
          {t.legend[agent.status] || agent.status}
        </span>
      </div>
      <dl className="mt-4 flex flex-col gap-2 text-[14px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline gap-3">
            <dt className="w-[160px] shrink-0 text-[var(--mu)]">{k}</dt>
            <dd className="mono">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** schema-form — declarative, read-only field rendering. */
export function SchemaFormPage({ page, t, lang }) {
  const fields =
    page.props && Array.isArray(page.props.fields) ? page.props.fields : null;
  if (!fields || fields.length === 0) {
    return <Note>{t.pageNoFields}</Note>;
  }
  return (
    <div className="flex max-w-[560px] flex-col gap-4">
      {fields.map((f) => (
        <label key={f.id} className="flex flex-col gap-1.5 text-[14px]">
          <span className="text-[var(--mu)]">{label(f.label, lang, f.id)}</span>
          {f.type === "toggle" ? (
            <span className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={!!f.value}
                disabled
                readOnly
                className="h-4 w-4 accent-[var(--sun)]"
              />
              <span className="mono text-[13px]">
                {f.value ? t.enabled : t.disabled}
              </span>
            </span>
          ) : f.type === "select" && Array.isArray(f.options) ? (
            <select
              disabled
              value={f.value == null ? "" : String(f.value)}
              className="rounded-xl border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] opacity-70"
            >
              <option value="">{f.value == null ? "—" : String(f.value)}</option>
              {f.options.map((o) => (
                <option key={String(o)} value={String(o)}>
                  {String(o)}
                </option>
              ))}
            </select>
          ) : (
            <input
              disabled
              value={f.value == null ? "" : String(f.value)}
              placeholder={t.disabled}
              className="mono rounded-xl border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] opacity-70"
            />
          )}
        </label>
      ))}
      <p className="text-[12px] text-[var(--mu)]">{t.formNote}</p>
    </div>
  );
}

/** timeline — read-only run table (the interactive timeline
 *  with replay lives on the command canvas). */
export function TimelinePage({ page, t, ctx }) {
  const source = (page.props && page.props.source) || "runs";
  if (source !== "runs") {
    return (
      <Note>
        {t.unknownSource}: <span className="mono">{String(source)}</span>
      </Note>
    );
  }
  const runs = runsInOrder(ctx.runtime);
  if (runs.length === 0) return <Note>{t.noRuns}</Note>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-start text-[14px]">
        <thead>
          <tr className="border-b border-[var(--line)] text-[13px] text-[var(--mu)]">
            {[t.run, t.colAgent, t.colState, t.mission, t.colElapsed].map((h, i) => (
              <th key={`h-${i}`} className="px-3 py-2 text-start font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => {
            const waiting =
              r.state === "waiting" && r.waitingReason
                ? ` (${t.waitingReasons[r.waitingReason] || r.waitingReason})`
                : "";
            return (
              <tr key={r.runId} className="border-b border-[rgba(56,232,255,.08)]">
                <td className="mono px-3 py-2" style={{ color: RUN_STATE_COLOR[r.state] }}>
                  {r.runId}
                </td>
                <td className="px-3 py-2">{r.agentId}</td>
                <td className="px-3 py-2" style={{ color: RUN_STATE_COLOR[r.state] }}>
                  {(t.runStates && t.runStates[r.state]) || r.state}
                  {waiting}
                </td>
                <td className="mono px-3 py-2">{r.missionId || "—"}</td>
                <td className="mono px-3 py-2">{secs(elapsedMs(r))}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** command-canvas — the canvas is hosted by the app shell on the
 *  home route; any other route gets a safe pointer, never a crash. */
export function CommandCanvasPage({ t, onNavigate }) {
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-[15px] text-[var(--mu)]">{t.canvasHosted}</p>
      <button
        type="button"
        onClick={() => onNavigate("/home")}
        className="btn-core rounded-full px-4 py-2 text-[14px] font-semibold transition hover:brightness-110"
      >
        {t.backToCanvas}
      </button>
    </div>
  );
}
