import React from "react";
import { SimulatedBadge } from "./SimulatedBadge";

interface SidebarProps {
  t: (key: string) => string;
}

export const Sidebar: React.FC<SidebarProps> = ({ t }) => {
  const items = [
    { key: "nav.home", icon: "⌂", active: true },
    { key: "nav.missions", icon: "🚀", active: false },
    { key: "nav.hubs", icon: "🌐", active: false },
    { key: "nav.agents", icon: "🤖", active: false },
    { key: "nav.models", icon: "🧠", active: false },
    { key: "nav.tools", icon: "🛠", active: false },
    { key: "nav.history", icon: "⏱", active: false },
    { key: "nav.pages", icon: "📄", active: false },
    { key: "nav.settings", icon: "⚙", active: false }
  ];

  return (
    <nav
      className="glass"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "6px",
        padding: "16px 12px",
        height: "100%",
        minHeight: "520px"
      }}
    >
      <div style={{ marginBottom: "10px", padding: "0 6px" }}>
        <SimulatedBadge label="OFFLINE NAV" />
      </div>

      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className="btn-ghost"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            textAlign: "start",
            padding: "10px 12px",
            borderColor: item.active ? "var(--sun)" : "transparent",
            background: item.active ? "rgba(56, 232, 255, 0.12)" : "transparent"
          }}
        >
          <span style={{ fontSize: "16px" }}>{item.icon}</span>
          <span style={{ fontSize: "13px", fontWeight: item.active ? 600 : 400 }}>
            {t(item.key)}
          </span>
        </button>
      ))}
    </nav>
  );
};