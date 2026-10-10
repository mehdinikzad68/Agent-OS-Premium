// Header with a LIVE connection-state badge (ported from the WSL canonical
// repo's connection-layer commit). The old static "Live" dot is replaced by
// the real connection state: the badge must never claim "live" for demo data.
import { useState, useRef, useEffect } from "react";
import { Radio } from "lucide-react";
import { APPROVER } from "../data.js";
import { useConnection } from "../connection/ConnectionProvider.jsx";

// Fallback English labels so the badge degrades gracefully if a translation
// key is missing (never a blank badge, never a crash).
const FALLBACK = {
  demo: "Demo",
  connected: "Connected",
  stale: "Stale",
  token_required: "Token Required",
  forbidden: "Forbidden",
  unavailable: "Unavailable",
  disconnected: "Disconnected",
  connecting: "Connecting...",
};

export default function Header({ t, lang, setLang }) {
  const { state, lastSuccessTime, connect, disconnect } = useConnection();
  const [open, setOpen] = useState(false);
  const [inputVal, setInputVal] = useState("");
  const [remember, setRemember] = useState(false);
  const menuRef = useRef(null);

  // Click-outside closes the token menu.
  useEffect(() => {
    const clickOut = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", clickOut);
    return () => document.removeEventListener("mousedown", clickOut);
  }, []);

  const handleConnect = () => {
    connect(inputVal.trim(), remember);
    setInputVal("");
    setOpen(false);
  };

  const handleDisconnect = () => {
    disconnect();
    setOpen(false);
  };

  const L = (key) => t[key] ?? FALLBACK[key] ?? key;

  let badgeColor = "var(--sun)";
  let badgeText = L("demo");
  let showPulse = false;

  switch (state) {
    case "connected":
      badgeColor = "var(--ok)";
      badgeText = L("connected");
      showPulse = true;
      break;
    case "stale": {
      badgeColor = "var(--sun)";
      const ts = lastSuccessTime
        ? new Date(lastSuccessTime).toLocaleTimeString(lang === "fa" ? "fa-IR" : "en-US")
        : "—";
      badgeText = `${L("stale")} (${ts})`;
      break;
    }
    case "token_required":
      badgeColor = "var(--sun)";
      badgeText = L("token_required");
      break;
    case "forbidden":
      badgeColor = "var(--bad)";
      badgeText = L("forbidden");
      break;
    case "unavailable":
      badgeColor = "var(--bad)";
      badgeText = L("unavailable");
      break;
    case "disconnected":
      badgeColor = "var(--bad)";
      badgeText = L("disconnected");
      break;
    case "connecting":
      badgeColor = "var(--sun)";
      badgeText = L("connecting");
      break;
    default:
      break;
  }

  return (
    <header className="relative z-20 flex flex-wrap items-center gap-4 border-b border-[var(--line)] bg-[rgba(2,8,16,.75)] px-5 py-3 backdrop-blur">
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
        <div className="relative hidden items-center gap-2 rounded-full border border-[var(--line)] px-3 py-1.5 md:flex">
          <Radio size={14} className="text-[var(--ok)]" />
          <span className="text-[14px] text-[var(--mu)]">{t.mission}</span>
          <span className="mono text-[14px]">wp-bioscentiran</span>
        </div>

        {/* Connection-state badge + token menu */}
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={open}
            className="flex items-center gap-2 rounded px-2 py-1 text-[14px] transition hover:bg-[rgba(255,255,255,.05)]"
            style={{ color: badgeColor }}
          >
            <i
              className={`h-2 w-2 rounded-full ${showPulse ? "dotlive" : ""}`}
              style={{ backgroundColor: badgeColor, color: badgeColor }}
            />
            {badgeText}
          </button>

          {open && (
            <div className="glass absolute end-0 z-50 mt-2 flex min-w-[240px] flex-col gap-3 rounded-xl p-4 shadow-xl">
              <input
                type="password"
                value={inputVal}
                onChange={(e) => setInputVal(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleConnect()}
                placeholder="Token"
                aria-label="Agent OS token"
                className="w-full rounded border border-[var(--line)] bg-[rgba(2,10,20,.6)] px-3 py-2 text-[14px] text-[var(--tx)] outline-none focus:border-[var(--sun)]"
              />
              <label className="flex cursor-pointer items-center gap-2 text-[13px] text-[var(--mu)]">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                {t.rememberMe ?? "Remember me"}
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleConnect}
                  className="btn-core flex-1 rounded-full px-3 py-1.5 text-[13px] font-semibold"
                >
                  {t.connect ?? "Connect"}
                </button>
                <button
                  type="button"
                  onClick={handleDisconnect}
                  className="flex-1 rounded-full border px-3 py-1.5 text-[13px] font-semibold"
                  style={{ borderColor: "var(--bad)", color: "var(--bad)" }}
                >
                  {t.disconnectBtn ?? "Disconnect"}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2.5 border-s border-[var(--line)] ps-3">
          <div className="grid h-9 w-9 place-items-center rounded-full bg-[linear-gradient(135deg,#0f6f8a,#06202e)] text-[14px] font-semibold ring-1 ring-[var(--line)]">
            {APPROVER.initials}
          </div>
          <div className="hidden leading-tight sm:block">
            <div className="text-[14px] font-medium">{APPROVER.name}</div>
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
