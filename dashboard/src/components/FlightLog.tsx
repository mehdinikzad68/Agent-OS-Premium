import React from "react";
import { SimulatedBadge } from "./SimulatedBadge";
import type { SimulatedFlightEvent } from "../fixtures/dashboardFixture";

interface FlightLogProps {
  events: SimulatedFlightEvent[];
  t: (key: string) => string;
}

export const FlightLog: React.FC<FlightLogProps> = ({ events, t }) => {
  return (
    <section
      className="glass"
      style={{
        padding: "16px 20px",
        margin: "0 16px 16px 16px",
        borderRadius: "14px",
        display: "flex",
        flexDirection: "column",
        gap: "10px"
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "16px", color: "var(--sun)" }}>⚡</span>
          <h3 className="disp" style={{ fontSize: "15px", color: "var(--sun2)" }}>
            {t("log.title")}
          </h3>
          <span className="pill tech" style={{ color: "var(--mu)" }}>
            {events.length} EVENTS RECORDED
          </span>
        </div>
        <SimulatedBadge label="STATIC AUDIT LOG" />
      </div>

      <div style={{ display: "flex", gap: "12px", overflowX: "auto", paddingBottom: "4px" }}>
        {events.map((ev) => (
          <div
            key={ev.seq}
            style={{
              minWidth: "260px",
              padding: "10px 14px",
              background: "rgba(2, 10, 20, 0.65)",
              border: "1px solid var(--line)",
              borderRadius: "10px"
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
              <span className="tech mono" style={{ fontSize: "11px", color: "var(--sun)" }}>
                #{ev.seq} {ev.kind}
              </span>
              <span className="tech mono" style={{ fontSize: "11px", color: "var(--mu)" }}>
                {ev.time}
              </span>
            </div>
            <div style={{ fontSize: "12px", color: "var(--tx)", lineHeight: "1.4" }}>
              {ev.summary}
            </div>
            <div className="tech" style={{ fontSize: "10px", color: "var(--mu)", marginTop: "4px" }}>
              src: {ev.source}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};