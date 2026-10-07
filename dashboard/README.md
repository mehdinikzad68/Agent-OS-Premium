# Agent OS — Neural Command Dashboard (Scaffold v0.1.0)

Independent React + TypeScript dashboard implementing the canonical Neural Command design specification (`docs/UI-Design/agent-os-neural-command-robot.html`).

## Architecture & Safety Boundary
- **Pure Offline Scaffold:** Operates completely without live backend APIs, WebSocket streams, or network fetches.
- **Strictly Simulated:** All telemetry, approvals, and events are loaded from explicit deterministic test fixtures (`src/fixtures/dashboardFixture.ts`).
- **Deterministic Canvas 2D:** The central neural command viewport is powered strictly by standard Browser Canvas 2D API using a Mulberry32 PRNG (zero Math.random) for 100% reproducible frames and pixel-level regression testing.
- **Zero Three.js / WebGL:** Adheres strictly to ADR-001.
- **Zero External CDNs:** Offline-first design with system fallback font stacks.

## Development Commands
```bash
# Typecheck
npm run typecheck

# Production Build
npm run build

# Local Development Server (Loopback only)
npm run dev
```