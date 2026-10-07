// To keep tokens out of the open scope, we inject the token provider
let getTokenProvider = () => "";

export function registerTokenProvider(provider) {
  getTokenProvider = provider;
}

export function sanitize(message) {
  if (!message) return "";
  let s = String(message);
  const token = getTokenProvider();
  if (token && token.length > 3) {
    s = s.split(token).join("[REDACTED]");
  }
  return s.replace(/Bearer\s+[A-Za-z0-9_\-\.]+/gi, "Bearer [REDACTED]");
}

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
      signal: controller.signal
    });
  } catch (error) {
    clearTimeout(timeoutId);
    let msg = error.name === "AbortError" && !options.signal?.aborted
      ? `Request timed out after ${timeoutMs}ms`
      : error.message;
    throw new Error(sanitize(msg));
  }

  clearTimeout(timeoutId);

  let data;
  try {
    data = await response.json();
  } catch(e) {
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