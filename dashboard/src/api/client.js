// Thin fetch wrapper for the Agent OS control-service HTTP API.
//
// Ported from the WSL canonical repo (dashboard/src/api/client.js) so the
// connection layer that already existed there is preserved when this project
// replaces it. Only cosmetic reformatting — the behaviour is unchanged.
//
// Contract (see docs/03-api-documentation.md in the backend repo):
//   - Base URL is same-origin in production (the backend serves the built UI
//     and /api together); in dev, Vite proxies /api to the control-service.
//     Either way this module only ever emits RELATIVE paths (/api/...), so no
//     absolute URL is hardcoded in the renderer source (enforced by
//     tests/contract.test.js: "renderer source contains no URL strings").
//   - Every /api/* call needs `Authorization: Bearer <token>`.
//   - The token is injected via a provider so it never lives in module state
//     that a stray console.log could leak; error messages are sanitized.
//
// This module is the ONLY place the UI performs network I/O. Adapters call it;
// renderers never do (skill 08: "the UI never builds URLs, only adapters do").

// Token provider is injected so the token never lives in importable module
// state. See registerTokenProvider below.
let getTokenProvider = () => "";

export function registerTokenProvider(provider) {
  getTokenProvider = provider;
}

/** Strip the live token (and any Bearer token) out of a message before it can
 *  reach the console, a toast, or an error boundary. */
export function sanitize(message) {
  if (!message) return "";
  let s = String(message);
  const token = getTokenProvider();
  if (token && token.length > 3) {
    s = s.split(token).join("[REDACTED]");
  }
  return s.replace(/Bearer\s+[A-Za-z0-9_\-\.]+/gi, "Bearer [REDACTED]");
}

/**
 * Perform one API call.
 * @param {string} method  HTTP method (GET/POST/DELETE/...)
 * @param {string} path    Path starting with "/api/" (other paths send no auth)
 * @param {{headers?:object, body?:any, timeoutMs?:number, signal?:AbortSignal}} options
 * @returns {Promise<any>} parsed JSON body
 * @throws {Error} sanitized message, with `.status` and `.reason` when the
 *                 server returned a typed error envelope.
 */
export async function api(method, path, options = {}) {
  const isApi = path.startsWith("/api/");
  const upperMethod = method.toUpperCase();
  const token = getTokenProvider();

  const headers = { ...options.headers };
  if (isApi && token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let body = options.body;
  if (body !== undefined && typeof body !== "string") {
    body = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }

  const timeoutMs = options.timeoutMs ?? 8000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  if (options.signal) {
    options.signal.addEventListener("abort", () => controller.abort());
  }

  let response;
  try {
    response = await fetch(path, {
      method: upperMethod,
      headers,
      body,
      signal: controller.signal,
    });
  } catch (error) {
    clearTimeout(timeoutId);
    let msg =
      error.name === "AbortError" && !options.signal?.aborted
        ? `Request timed out after ${timeoutMs}ms`
        : error.message;
    throw new Error(sanitize(msg));
  }

  clearTimeout(timeoutId);

  let data;
  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    const errObj = data.error || {};
    const errorMsg = sanitize(errObj.message || `HTTP ${response.status}`);
    const error = new Error(errorMsg);
    error.status = response.status;
    error.reason = errObj.reason;
    throw error;
  }

  return data;
}
