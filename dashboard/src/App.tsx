import React, { useState, useEffect } from "react";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { ApprovalGate } from "./components/ApprovalGate";
import { FlightLog } from "./components/FlightLog";
import { NeuralScene } from "./scene/NeuralScene";
import { DASHBOARD_FIXTURE } from "./fixtures/dashboardFixture";
import { en } from "./i18n/en";
import { fa } from "./i18n/fa";
import type { TranslationKey } from "./i18n/en";

const LANG_KEY = "agent_os_dashboard_lang";

export const App: React.FC = () => {
  const [lang, setLang] = useState<"en" | "fa">(() => {
    try {
      const saved = localStorage.getItem(LANG_KEY);
      if (saved === "fa" || saved === "en") return saved;
    } catch {
      // LocalStorage access fallback
    }
    return "en";
  });

  const [isReducedMotion, setIsReducedMotion] = useState(false);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
    document.body.className = `deck ${lang === "fa" ? "f-fa" : "f-en"}`;
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch {
      // Storage unavailable
    }
  }, [lang]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setIsReducedMotion(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsReducedMotion(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const t = (key: string): string => {
    const dict = lang === "fa" ? fa : en;
    return dict[key as TranslationKey] || key;
  };

  const toggleLang = () => {
    setLang((prev) => (prev === "en" ? "fa" : "en"));
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <Header
        missionTitle={DASHBOARD_FIXTURE.missionTitle}
        lang={lang}
        onToggleLang={toggleLang}
      />

      <div className="dashboard-grid">
        <Sidebar t={t} />
        <NeuralScene nodes={DASHBOARD_FIXTURE.nodes} isFrozen={isReducedMotion} />
        <ApprovalGate approvals={DASHBOARD_FIXTURE.approvals} t={t} />
      </div>

      <FlightLog events={DASHBOARD_FIXTURE.events} t={t} />
    </div>
  );
};