// Inspector for the shared-memory node (skill 05).
//
// Shows the three separate facts — authorized access,
// available connections, actual retrieval events —
// plus source references for returned MOCK items.
// Read-only: no write action exists in this panel.
import { X } from "lucide-react";

export default function MemoryInspector({
  t,
  providerName,
  connections,
  policy,
  log,
  lastResult,
  onClose,
}) {
  const grantedScopes = [...new Set(policy.grants.map((g) => g.scope))];
  const statusDot = (ok) => ({
    background: ok ? "#5ff0a8" : "#ff5c7a",
  });

  return (
    <div className="absolute inset-x-0 top-2 z-20 flex justify-center pointer-events-none">
      <div
        dir="ltr"
        className="rise glass pointer-events-auto relative w-[330px] px-4 py-3"
      >
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute top-2.5 text-[var(--mu)] hover:text-white ltr:right-2.5 rtl:left-2.5"
        >
          <X size={16} />
        </button>

        <div className="flex items-center gap-2">
          <span className="disp text-[20px] leading-none">{t.memoryNode}</span>
          <span className="mock-tag">MOCK</span>
        </div>
        <div className="mt-1 text-[14px] text-[var(--mu)]">
          {t.memoryProvider}: <span className="mono">{providerName}</span>
          <span className="ms-2 text-[12px] text-[var(--mu)]">
            · {t.memoryReadOnly}
          </span>
        </div>

        <div className="mt-3 text-[12px] font-semibold text-[var(--sun2)]">
          {t.memoryConnections}
        </div>
        <ul className="mt-1 flex flex-col gap-1 text-[12px]">
          {connections.map((c) => (
            <li key={c.id} className="flex items-center gap-2">
              <i
                className="h-1.5 w-1.5 rounded-full"
                style={statusDot(c.state === "enabled")}
              />
              <span className="mono">
                {c.from} → {c.to}
              </span>
              <span className="text-[var(--mu)]">
                {c.state === "enabled" ? t.enabled : t.disabled}
              </span>
            </li>
          ))}
          {connections.length === 0 && (
            <li className="text-[var(--mu)]">{t.memoryNoConnections}</li>
          )}
        </ul>

        <div className="mt-3 text-[12px] font-semibold text-[var(--sun2)]">
          {t.memoryReadAccess}
        </div>
        <ul className="mt-1 flex flex-col gap-1 text-[12px]">
          {policy.grants.map((g) => (
            <li key={`${g.agentId}:${g.scope}`} className="mono">
              {g.agentId} <span className="text-[var(--mu)]">→</span> {g.scope}
            </li>
          ))}
          {policy.grants.length === 0 && (
            <li className="text-[var(--mu)]">{t.memoryNoGrants}</li>
          )}
        </ul>

        {grantedScopes.length > 0 && (
          <>
            <div className="mt-3 text-[12px] font-semibold text-[var(--sun2)]">
              {t.memoryScopes}
            </div>
            <ul className="mt-1 flex flex-col gap-1 text-[12px]">
              {grantedScopes.map((s) => (
                <li key={s} className="mono">
                  {s}
                </li>
              ))}
            </ul>
          </>
        )}

        <div className="mt-3 text-[12px] font-semibold text-[var(--sun2)]">
          {t.memoryRequests}
        </div>
        <ul className="mt-1 flex max-h-[130px] flex-col gap-1 overflow-auto text-[12px]">
          {log.map((e) => (
            <li key={e.id} className="flex items-center gap-2">
              <i
                className="h-1.5 w-1.5 rounded-full"
                style={statusDot(e.status === "allowed")}
              />
              <span className="mono">{e.agentId}</span>
              <span className="text-[var(--mu)]">{e.scope}</span>
              {e.status === "allowed" ? (
                <span className="mono ms-auto text-[11px] text-[#c4f7dc]">
                  {e.count} item{e.count === 1 ? "" : "s"}
                </span>
              ) : (
                <span className="ms-auto text-[11px] text-[#ffc0ca]">
                  {e.status === "denied" ? t.memoryDenied : t.memoryError}
                </span>
              )}
              <span className="text-[11px] text-[var(--mu)]">{e.at}</span>
            </li>
          ))}
          {log.length === 0 && (
            <li className="text-[var(--mu)]">{t.memoryNoRequests}</li>
          )}
        </ul>

        {lastResult &&
          lastResult.items &&
          lastResult.items.length > 0 && (
            <>
              <div className="mt-3 text-[12px] font-semibold text-[var(--sun2)]">
                {t.memorySources}
              </div>
              <ul className="mt-1 flex flex-col gap-1 text-[11px]">
                {lastResult.items.map((item) => (
                  <li key={item.id} className="mono text-[var(--mu)]">
                    {item.source}
                  </li>
                ))}
              </ul>
            </>
          )}
      </div>
    </div>
  );
}
