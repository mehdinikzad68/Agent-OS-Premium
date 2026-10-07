import React, { createContext, useState, useEffect, useCallback, useContext } from "react";
import { api, registerTokenProvider } from "../api/client";

export const ConnectionContext = createContext(null);

export function useConnection() {
  return useContext(ConnectionContext);
}

export function ConnectionProvider({ children }) {
  const [token, setTokenState] = useState(() => {
    return sessionStorage.getItem("agent_os_token") || localStorage.getItem("agent_os_token") || "";
  });

  const [state, setState] = useState(() => token ? "connecting" : "demo");
  const [lastSuccessTime, setLastSuccessTime] = useState(null);

  // Sync token to API client
  useEffect(() => {
    registerTokenProvider(() => token);
  }, [token]);

  const connect = useCallback((newToken, remember) => {
    setTokenState(newToken);
    if (!newToken) {
      sessionStorage.removeItem("agent_os_token");
      localStorage.removeItem("agent_os_token");
      setState("demo");
      return;
    }
    if (remember) {
      localStorage.setItem("agent_os_token", newToken);
      sessionStorage.removeItem("agent_os_token");
    } else {
      sessionStorage.setItem("agent_os_token", newToken);
      localStorage.removeItem("agent_os_token");
    }
    setState("connecting");
  }, []);

  const disconnect = useCallback(() => {
    setTokenState("");
    sessionStorage.removeItem("agent_os_token");
    localStorage.removeItem("agent_os_token");
    setState("demo");
    setLastSuccessTime(null);
  }, []);

  const pingStatus = useCallback(async () => {
    if (!token) return;
    try {
      await api("GET", "/api/status");
      setState("connected");
      setLastSuccessTime(Date.now());
    } catch (e) {
      if (e.status === 401) {
        setState("token_required");
      } else if (e.status === 403) {
        setState("forbidden");
      } else if (e.status >= 500) {
        setState("unavailable");
      } else {
        setState((prev) => prev === "connected" || prev === "stale" ? "stale" : "disconnected");
      }
    }
  }, [token]);

  useEffect(() => {
    if (state === "connecting") {
      pingStatus();
    }
  }, [state, pingStatus]);

  useEffect(() => {
    if (!token) return;
    const interval = setInterval(() => {
      if (!document.hidden) {
        pingStatus();
      }
    }, 8000);
    return () => clearInterval(interval);
  }, [token, pingStatus]);

  return (
    <ConnectionContext.Provider value={{ token, state, lastSuccessTime, connect, disconnect }}>
      {children}
    </ConnectionContext.Provider>
  );
}