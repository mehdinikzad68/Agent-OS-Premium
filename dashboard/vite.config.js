import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: the React app is served by Vite on 5173, but the Agent OS
// control-service is a separate process on 127.0.0.1:8470. Same-origin /api
// calls are forwarded here so the browser never sees a cross-origin request
// (the backend is loopback-only and sends no CORS headers).
//
// In production the built UI is served BY the backend itself, so /api is
// already same-origin and no proxy is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8470",
    },
  },
});
