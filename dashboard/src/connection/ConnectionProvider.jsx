// Connection state machine for the Agent OS backend.
//
// Ported from the WSL canonical repo (dashboard/src/connection/ConnectionProvider.jsx)
// with two deliberate deviations, both documented at the point they apply:
//   1. SECURITY: the token is kept in sessionStorage by default. `remember`
//      (localStorage) is opt-in, because the backend is loopback-only and a
//      persistent token on disk is a larger blast radius than a session one.
//   2. The `demo` state is the default when no token exists — the UI must show
//      demo data as demo (skill 05 / skill 08 labelling), never as live.
//
// States (drives the Header badge):
//   demo            no token -> the mock adapter is in charge, no network
//   connecting      token present, first ping in flight
//   connected       last ping succeeded
//   stale           a later ping failed but we were once connected
//   token_required  401 -> the token is missing/wrong
//   forbidden       403 -> authenticated but not allowed
//   unavailable     5xx -> the service is up but erroring
//   disconnected    network-level failure (backend not running / unreachable)

import React, {
  createContext,
  useState,
  useEffect,
  useCallback,
  useContext,
} from "react";
import { api, registerTokenProvider } from "../api/client.js";

export const ConnectionContext = createContext(null);

export function useConnection() {
  return useContext(ConnectionContext);
}

const TOKEN_KEY = "agent_os_token";

/** Read a stored token. sessionStorage first (session-scoped, the default),
 *  then localStorage (only ever written when the user opts into "remember"). */
function readStoredToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function clearStoredToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable — nothing to clear */
  }
}

function writeStoredToken(token, remember) {
  try {
    // Default is sessionStorage: the token dies with the tab. A persistent
    // token is only written when the user explicitly asks for it.
    if (remember) {
      localStorage.setItem(TOKEN_KEY, token);
      sessionStorage.removeItem(TOKEN_KEY);
    } else {
      sessionStorage.setItem(TOKEN_KEY, token);
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    /* storage unavailable — the token still works for this render tree */
  }
}

export function ConnectionProvider({ children }) {
  const [token, setTokenState] = useState(readStoredToken);
  const [state, setState] = useState(() => (readStoredToken() ? "connecting" : "demo"));
  const [lastSuccessTime, setLastSuccessTime] = useState(null);

  // Sync token into the API client's provider (kept out of module state).
  useEffect(() => {
    registerTokenProvider(() => token);
  }, [token]);

  const connect = useCallback((newToken, remember) => {
    const trimmed = (newToken || "").trim();
    if (!trimmed) {
      setTokenState("");
      clearStoredToken();
      setState("demo");
      setLastSuccessTime(null);
      return;
    }
    setTokenState(trimmed);
    writeStoredToken(trimmed, remember);
    setState("connecting");
  }, []);

  const disconnect = useCallback(() => {
    setTokenState("");
    clearStoredToken();
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
        // Once connected, a transient failure is "stale" (we know the service
        // existed) rather than a flat "disconnected".
        setState((prev) =>
          prev === "connected" || prev === "stale" ? "stale" : "disconnected"
        );
      }
    }
  }, [token]);

  // First ping whenever we enter "connecting".
  useEffect(() => {
    if (state === "connecting") {
      pingStatus();
    }
  }, [state, pingStatus]);

  // Keep-alive ping while a token exists and the tab is visible.
  useEffect(() => {
    if (!token) return;
    const iv = setInterval(() => {
      if (!document.hidden) pingStatus();
    }, 8000);
    return () => clearInterval(iv);
  }, [token, pingStatus]);

  const value = React.useMemo(
    () => ({ token, state, lastSuccessTime, connect, disconnect }),
    [token, state, lastSuccessTime, connect, disconnect]
  );

  return (
    <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>
  );
}
