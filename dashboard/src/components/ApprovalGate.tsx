import React from "react";
import { SimulatedBadge } from "./SimulatedBadge";
import type { SimulatedApproval } from "../fixtures/dashboardFixture";

interface ApprovalGateProps {
  approvals: SimulatedApproval[];
  t: (key: string) => string;
}

export const ApprovalGate: React.FC<ApprovalGateProps> = ({ approvals, t }) => {
  return (
    <aside
      className="glass"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "14px",
        padding: "16px",
        height: "100%",
        minHeight: "520px"
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ color: "var(--await)" }}>🛡</span>
          <h2 className="disp" style={{ fontSize: "16px", color: "var(--tx)" }}>
            {t("gate.title")}
          </h2>
        </div>
        <SimulatedBadge label="READ-ONLY" />
      </div>

      <div style={{ fontSize: "12px", color: "var(--mu)" }}>
        {t("gate.tierWarning")}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "12px", flex: 1, overflowY: "auto" }}>
        {approvals.map((app) => (
          <div
            key={app.id}
            style={{
              padding: "12px",
              borderRadius: "12px",
              background: "rgba(2, 10, 20, 0.7)",
              border: "1px solid var(--line)"
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
              <span className="pill tech" style={{ color: "var(--await)" }}>{app.tier}</span>
              <span className="tech" style={{ fontSize: "11px", color: "var(--mu)" }}>{app.id}</span>
            </div>

            <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "4px" }}>
              {app.title}
            </div>

            <div className="tech" style={{ fontSize: "11px", color: "var(--mu)", marginBottom: "8px" }}>
              {app.targetResource}
            </div>

            <pre
              className="tech mono"
              style={{
                fontSize: "11px",
                background: "var(--code-bg)",
                padding: "8px",
                borderRadius: "6px",
                overflowX: "auto",
                color: "var(--sun2)",
                marginBottom: "10px"
              }}
            >
              {app.diffSummary}
            </pre>

            <div style={{ display: "flex", gap: "8px" }}>
              <button type="button" className="btn-core" style={{ flex: 1, opacity: 0.6, cursor: "not-allowed" }} disabled>
                {t("gate.approve")}
              </button>
              <button type="button" className="btn-ghost" style={{ flex: 1, opacity: 0.6, cursor: "not-allowed" }} disabled>
                {t("gate.reject")}
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
};