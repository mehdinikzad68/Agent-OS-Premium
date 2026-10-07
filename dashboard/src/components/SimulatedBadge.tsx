import React from "react";

interface SimulatedBadgeProps {
  label?: string;
}

export const SimulatedBadge: React.FC<SimulatedBadgeProps> = ({ label = "SIMULATED" }) => {
  return (
    <span className="badge-simulated" title="Mock / Development Fixture — No Live API Connected">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
      {label}
    </span>
  );
};