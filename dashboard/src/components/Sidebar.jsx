// Minified name in bundle: px.
import { useState } from "react";
import { Bot, CircleQuestionMark, Cpu, FileText, History, House, Network, Rocket, Settings, Wrench } from "lucide-react";

// sx
const NAV_ICONS = [House, Rocket, Network, Bot, Cpu, Wrench, History, FileText, Settings];

export default function Sidebar({ t }) {
  const [active, setActive] = useState(0);
  const badges = { 1: 3, 3: 6 };
  return (
    <nav className="glass scroll flex gap-1 overflow-x-auto p-2 lg:row-span-2 lg:flex-col lg:overflow-visible">
      {t.nav.map((label, i) => {
        const Icon = NAV_ICONS[i];
        const on = active === i;
        return (
          <button
            key={i}
            onClick={() => setActive(i)}
            className="navi relative flex shrink-0 items-center gap-3 rounded-xl px-3 py-2.5 text-start"
            style={{
              background: on ? "linear-gradient(90deg,rgba(56,232,255,.14),rgba(56,232,255,.02))" : "transparent",
              color: on ? "#e9fdff" : "var(--mu)",
            }}
          >
            {on && (
              <span
                className="absolute inset-y-2 w-[3px] rounded-full bg-[var(--sun)] ltr:left-0 rtl:right-0"
                style={{ boxShadow: "0 0 10px #38e8ff" }}
              />
            )}
            <Icon size={18} />
            {label}
            {badges[i] && (
              <span className="mono ms-auto rounded-full bg-[rgba(255,154,82,.15)] px-2 text-[13px] text-[var(--await)]">{badges[i]}</span>
            )}
          </button>
        );
      })}
      <button className="navi mt-auto hidden items-center gap-3 rounded-xl px-3 py-2.5 text-[var(--mu)] lg:flex">
        <CircleQuestionMark size={18} />
        {t.help}
      </button>
    </nav>
  );
}
