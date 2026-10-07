import React from "react";
import { SimulatedBadge } from "./SimulatedBadge";

interface HeaderProps {
  missionTitle: string;
  lang: "en" | "fa";
  onToggleLang: () => void;
}

export const Header: React.FC<HeaderProps> = ({ missionTitle, lang, onToggleLang }) => {
  return (
    <header
      className="glass"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "12px 20px",
        margin: "12px 16px 0 16px",
        borderRadius: "14px"
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: "20px", color: "var(--sun)" }}>⬡</span>
          <span className="disp" style={{ fontSize: "18px", color: "var(--sun2)", letterSpacing: "0.08em" }}>
            AGENT OS
          </span>
          <span style={{ color: "var(--mu)", fontSize: "14px" }}>/ Neural Command</span>
        </div>
        <div className="pill">
          <span className="tech" style={{ color: "var(--tx)" }}>{missionTitle}</span>
        </div>
        <SimulatedBadge label="DISCONNECTED / SIMULATED" />
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
        <button
          type="button"
          className="btn-ghost"
          onClick={onToggleLang}
          style={{ display: "flex", alignItems: "center", gap: "6px" }}
        >
          <span style={{ color: "var(--mu)" }}>LANG:</span>
          <span className="tech" style={{ fontWeight: 600 }}>{lang.toUpperCase()}</span>
        </button>
      </div>
    </header>
  );
};