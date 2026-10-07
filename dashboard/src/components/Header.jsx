// Minified name in bundle: cx.
import { useState, useRef, useEffect } from "react";
import { Radio } from "lucide-react";
import { APPROVER } from "../data";
import { useConnection } from "../connection/ConnectionProvider";

export default function Header({ t, lang, setLang }) {
  const { state, lastSuccessTime, connect, disconnect } = useConnection();
  const [open, setOpen] = useState(false);
  const [inputVal, setInputVal] = useState("");
  const [remember, setRemember] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    const clickOut = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", clickOut);
    return () => document.removeEventListener("mousedown", clickOut);
  }, []);

  const handleConnect = () => {
    connect(inputVal.trim(), remember);
    setOpen(false);
  };

  const handleDisconnect = () => {
    disconnect();
    setOpen(false);
  };

  let badgeColor = "var(--sun)";
  let badgeText = t.demo || "Demo";
  let showPulse = false;

  switch (state) {
    case "connected":
      badgeColor = "var(--ok)";
      badgeText = t.connected || "Connected";
      showPulse = true;
      break;
    case "stale":
      badgeColor = "var(--sun)";
      const ts = lastSuccessTime ? new Date(lastSuccessTime).toLocaleTimeString(lang === "fa" ? "fa-IR" : "en-US") : "—";
      badgeText = (t.stale || "Stale") + ` (${ts})`;
      showPulse = false;
      break;
    case "token_required":
      badgeColor = "var(--sun)";
      badgeText = t.token_required || "Token Required";
      showPulse = false;
      break;
    case "forbidden":
      badgeColor = "var(--bad)";
      badgeText = t.forbidden || "Forbidden";
      showPulse = false;
      break;
    case "unavailable":
      badgeColor = "var(--bad)";
      badgeText = t.unavailable || "Unavailable";
      showPulse = false;
      break;
    case "disconnected":
      badgeColor = "var(--bad)";
      badgeText = t.disconnected || "Disconnected";
      showPulse = false;
      break;
    case "connecting":
      badgeColor = "var(--sun)";
      badgeText = t.connecting || "Connecting...";
      showPulse = false;
      break;
  }

  return (
    <header className="flex flex-wrap items-center gap-4 border-b border-[var(--line)] bg-[rgba(2,8,16,.75)] px-5 py-3 backdrop-blur z-20 relative">
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
        <div className="hidden items-center gap-2 rounded-full border border-[var(--line)] px-3 py-1.5 md:flex relative">
          <Radio size={14} className="text-[var(--ok)]" />
          <span className="text-[14px] text-[var(--mu)]">{t.mission}</span>
          <span className="mono text-[14px]">wp-bioscentiran</span>
        </div>

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="flex items-center gap-2 text-[14px] px-2 py-1 rounded hover:bg-[rgba(255,255,255,.05)] transition"
            style={{ color: badgeColor }}
          >
            <i
              className={`h-2 w-2 rounded-full ${showPulse ? 'dotlive' : ''}`}
              style={{ backgroundColor: badgeColor }}
            />
            {badgeText}
          </button>

          {open && (
            <div className="glass absolute right-0 mt-2 p-4 min-w-[240px] flex flex-col gap-3 rounded-xl shadow-xl z-50">
              <input
                type="password"
                value={inputVal}
                onChange={(e) => setInputVal(e.target.value)}
                placeholder="Token"
                className="w-full bg-[rgba(2,10,20,.6)] border border-[var(--line)] text-[var(--tx)] px-3 py-2 rounded text-[14px] outline-none focus:border-[var(--sun)]"
              />
              <label className="flex items-center gap-2 text-[13px] text-[var(--mu)] cursor-pointer">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                Remember me
              </label>
              <div className="flex gap-2">
                <button type="button" onClick={handleConnect} className="btn-core flex-1 text-[13px] py-1.5">Connect</button>
                <button type="button" onClick={handleDisconnect} className="btn-ghost flex-1 text-[13px] py-1.5" style={{ borderColor: 'var(--bad)', color: 'var(--bad)' }}>Disconnect</button>
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
