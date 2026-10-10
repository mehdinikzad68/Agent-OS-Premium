// Canvas 2D scene + HTML overlay labels (minified name in bundle: As).
//
// Extended for interactive editing (phase 3):
// - node dragging with pointer capture (coordinator stays fixed,
//   locked nodes cannot move, positions clamp into the canvas)
// - fiber curvature editing (view-only geometry)
// - endpoint reconnection with snap, valid-target highlighting,
//   invalid-target feedback and cancel-on-empty-space
// - connection selection with a hit area wider than the visible fiber
// - a non-drag connect flow (source -> Connect to… -> target + type)
//
// The animation loop reads a mutable ref (never React state per
// frame). All pointer math is coordinate-based, so RTL and LTR
// behave identically.
import { useEffect, useMemo, useRef, useState } from "react";
import { Scissors } from "lucide-react";
import { STATUS_COLOR, SUN, MAG, hexA } from "./colors.js";
import { buildHead } from "./head.js";
import {
  computeLayout,
  strandAt,
  strandMidpoint,
  nearestStrand,
  clampPosition,
} from "./layout.js";
import { paintBackdrop } from "./backdrop.js";
import { mulberry32 } from "./random.js";
import { cmdFor } from "../data.js";
import { compatibleTypes } from "../model/connections.js";
import { screenToWorld, setPosition, setFiberMidpoint } from "../model/view.js";
import { RUN_STATE_COLOR } from "./colors.js";
import ConnectionPicker from "../components/ConnectionPicker.jsx";

// Deterministic satellite placement around the parent
// node (skill 06): depth-1 children on an inner ring,
// deeper descendants on outer rings. Shared by the
// connector lines and the satellite buttons so both
// always agree on positions.
function satellitePos(parent, sats, target) {
  const idx = sats.indexOf(target);
  const angle = (idx / Math.max(1, sats.length)) * Math.PI * 2 - Math.PI / 2;
  const radius = 84 + (target.depth - 1) * 52;
  return { x: parent.x + Math.cos(angle) * radius, y: parent.y + Math.sin(angle) * radius };
}

// Compact elapsed-time label for satellite nodes.
function formatElapsed(run) {
  if (run.startedAt == null) return "—";
  const end = run.endedAt ?? run.lastEvent?.occurredAt ?? run.startedAt;
  const s = Math.max(0, Math.round((end - run.startedAt) / 1000));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/**
 * Optional (not in the original):
 *   seed       number  -> head + backdrop use Mulberry32(seed) instead of Math.random
 *   frozenTime number  -> scene clock pinned to this many seconds (animation stops)
 * Without them the scene behaves exactly like the original bundle.
 */
export default function NeuralScene({
  agents,
  connections,
  selected,
  setSelected,
  highlight,
  query,
  labelFor,
  coreLabel,
  burst,
  rtl,
  seed,
  frozenTime,
  view,
  onViewChange,
  onViewSnapshot,
  kinds,
  coordinatorId,
  registry,
  mode,
  selectedConnection,
  setSelectedConnection,
  onProposeConnection,
  onDisconnectConnection,
  connectFrom,
  setConnectFrom,
  strings,
  flash,
  memoryEvent,
  clusters,
  expandedClusters,
  subtrees,
  onToggleCluster,
  onSelectRun,
  selectedRun,
}) {
  const wrapRef = useRef();
  const canvasRef = useRef();
  const [size, setSize] = useState({ W: 800, H: 520 });
  const [hover, setHover] = useState(null);
  const [picker, setPicker] = useState(null);
  const head = useMemo(
    () => buildHead(3600, seed == null ? Math.random : mulberry32(seed)),
    [seed]
  );

  // Mutable interaction state — deliberately NOT React state so the
  // animation loop and pointer handlers stay in sync without renders.
  const interaction = useRef(null);
  const suppressClick = useRef(false);

  useEffect(() => {
    const ro = new ResizeObserver(([entry]) => {
      const r = entry.contentRect;
      setSize({ W: Math.max(300, r.width), H: Math.max(380, r.height) });
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(
    () =>
      computeLayout(
        agents,
        connections,
        size.W,
        size.H,
        view.positions,
        view.fiberGeometry,
        coordinatorId
      ),
    [agents, connections, size, view, coordinatorId]
  );
  const byId = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);
  const q = query.trim().toLowerCase();
  const match = (a) => !q || a.name.toLowerCase().includes(q) || a.id.includes(q);
  const focus = selected || highlight || hover;
  const linked = (id) =>
    connections.some(
      (l) => (l.from === focus && l.to === id) || (l.to === focus && l.from === id)
    );
  const dimNode = (id) =>
    (q && !match(byId[id])) ||
    (focus && focus !== id && focus !== coordinatorId && id !== coordinatorId && !linked(id));

  // Nodes that are valid targets of the non-drag connect flow.
  const connectTargets = useMemo(() => {
    if (!connectFrom) return [];
    const targets = [];
    for (const a of agents) {
      if (a.id === connectFrom) continue;
      if (
        compatibleTypes(registry, connections, { from: connectFrom, to: a.id })
          .length > 0
      ) {
        targets.push(a.id);
      }
    }
    return targets;
  }, [connectFrom, registry, agents, connections]);

  // latest render values for the draw loop
  const live = useRef({});
  live.current = {
    L: layout,
    byId,
    focus,
    p: q,
    match,
    dimNode,
    connectFrom,
    connectTargets,
    selectedConnection,
  };

  // burst comets fired on selection
  const bursts = useRef([]);
  useEffect(() => {
    burst?.id && bursts.current.push({ id: burst.id, t0: performance.now() });
  }, [burst]);

  // memory retrieval pulses (skill 05) — fired by
  // retrieval events, never by a timer.
  const memPulses = useRef([]);
  useEffect(() => {
    memoryEvent &&
      memPulses.current.push({ ...memoryEvent, t0: performance.now() });
  }, [memoryEvent]);

  // keep the latest frozenTime visible to the loop without restarting it
  const frozen = useRef(frozenTime);
  frozen.current = frozenTime;

  // Escape cancels, in order: picker -> active drag -> connect flow -> selection.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (picker) {
        setPicker(null);
        setConnectFrom(null);
        return;
      }
      if (interaction.current) {
        interaction.current = null;
        return;
      }
      if (connectFrom) {
        setConnectFrom(null);
        return;
      }
      if (selectedConnection) {
        setSelectedConnection(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    const cv = canvasRef.current;
    const g = cv.getContext("2d");
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const { W, H } = size;
    cv.width = W * dpr;
    cv.height = H * dpr;
    cv.style.width = W + "px";
    cv.style.height = H + "px";

    const backdrop = paintBackdrop(W, H, dpr, seed == null ? Math.random : mulberry32((seed ^ 0x9e3779b9) >>> 0));
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf;
    const start = performance.now();
    const proj = new Float32Array((head.length / 4) * 3);

    const frame = (now) => {
      const t = frozen.current != null ? frozen.current : ((now - start) / 1e3) * (reduced ? 0.25 : 1);
      const { L, byId, focus, p: q, match, dimNode } = live.current;
      const { C, R, nodes, fibers } = L;

      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.globalCompositeOperation = "source-over";
      g.drawImage(backdrop, 0, 0, W, H);
      g.globalCompositeOperation = "lighter";

      const hermesDim = q && !match(byId[coordinatorId]);
      const bursting = bursts.current.length ? 1 : 0;

      const ring = (x, y, rx, ry, a, lw, dash, off, color = SUN) => {
        g.save();
        g.strokeStyle = hexA(color, a);
        g.lineWidth = lw;
        if (dash) {
          g.setLineDash(dash);
          g.lineDashOffset = off;
        }
        g.beginPath();
        g.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
        g.stroke();
        g.restore();
      };

      // halo rings above the head
      const haloY = C.y - R * 1.5;
      ring(C.x, haloY, R * 1.9, R * 0.34, 0.16, 1.2, null, 0);
      ring(C.x, haloY, R * 1.45, R * 0.24, 0.3, 2, [R * 0.9, R * 0.3, R * 0.2, R * 0.4], t * 22);
      ring(C.x, haloY + R * 0.06, R * 0.8, R * 0.12, 0.45, 1.5, [8, 6], -t * 30);

      // base cone + pedestal rings
      const baseY = C.y + R * 1.42;
      const cone = g.createLinearGradient(0, C.y + R * 0.6, 0, baseY + R * 0.3);
      cone.addColorStop(0, "rgba(56,232,255,0)");
      cone.addColorStop(1, "rgba(56,232,255,.22)");
      g.fillStyle = cone;
      g.beginPath();
      g.moveTo(C.x - R * 0.35, C.y + R * 0.9);
      g.lineTo(C.x + R * 0.35, C.y + R * 0.9);
      g.lineTo(C.x + R * 0.8, baseY);
      g.lineTo(C.x - R * 0.8, baseY);
      g.fill();
      ring(C.x, baseY, R * 0.8, R * 0.16, 0.7, 2.2, null, 0);
      ring(C.x, baseY, R * 1.35, R * 0.27, 0.32, 1.4, [R * 0.6, R * 0.15], -t * 18);
      ring(C.x, baseY + R * 0.06, R * 2.1, R * 0.42, 0.14, 1, [3, 9], t * 10);
      ring(C.x, baseY + R * 0.1, R * 2.9, R * 0.58, 0.07, 1, null, 0);

      const pool = g.createRadialGradient(C.x, baseY, 0, C.x, baseY, R * 0.9);
      pool.addColorStop(0, "rgba(120,240,255,.45)");
      pool.addColorStop(1, "rgba(56,232,255,0)");
      g.fillStyle = pool;
      g.beginPath();
      g.ellipse(C.x, baseY, R * 0.9, R * 0.2, 0, 0, Math.PI * 2);
      g.fill();

      // purple horizon line
      const horizon = g.createLinearGradient(C.x - W * 0.44, 0, C.x + W * 0.44, 0);
      horizon.addColorStop(0, hexA(MAG, 0));
      horizon.addColorStop(0.4, hexA(MAG, 0.55));
      horizon.addColorStop(0.5, hexA(MAG, 0.15));
      horizon.addColorStop(0.6, hexA(MAG, 0.55));
      horizon.addColorStop(1, hexA(MAG, 0));
      g.strokeStyle = horizon;
      g.lineWidth = 1.6;
      g.beginPath();
      g.moveTo(C.x - W * 0.44, C.y + R * 0.05);
      g.lineTo(C.x + W * 0.44, C.y + R * 0.05);
      g.stroke();

      // fibers
      const stroke = (pts, col, a, lw) => {
        g.strokeStyle = hexA(col, a);
        g.lineWidth = lw;
        g.beginPath();
        g.moveTo(pts[0], pts[1]);
        for (let i = 2; i < pts.length; i += 2) g.lineTo(pts[i], pts[i + 1]);
        g.stroke();
      };

      const fiberState = fibers.map((f) => {
        const from = byId[f.from];
        const to = byId[f.to];
        const st =
          to.status === "running" && from.status !== "running" && from.id !== coordinatorId
            ? from.status
            : to.status;
        const active = focus && (f.from === focus || f.to === focus);
        const dim = (focus && !active) || (q && !(match(from) || match(to)));
        const disabled = f.state === "disabled";
        return { f, st, active, dim, disabled, col: disabled ? "#6b7fa6" : STATUS_COLOR[st] };
      });

      fiberState.forEach(({ f, st, active, dim, disabled, col }) => {
        const off = st === "offline" || disabled;
        off && g.setLineDash([4, 7]);
        f.strands.forEach((pts, i) => {
          const mid = i === Math.floor(f.strands.length / 2);
          const c = !off && i % 3 === 1 ? "#5ff0a8" : col;
          const a = dim ? 0.05 : off ? 0.14 : active ? 0.6 : 0.26;
          !off && !dim && stroke(pts, c, a * 0.25, mid ? 7 : 3.5);
          stroke(pts, c, a, mid ? 1.6 : 1);
        });
        g.setLineDash([]);
      });

      // comets
      const comet = (pts, pos, col, r, a) => {
        for (let k = 0; k < 6; k++) {
          const [x, y] = strandAt(pts, pos - k * 0.012);
          if (pos - k * 0.012 < 0) break;
          g.fillStyle = hexA(col, a * (1 - k / 6));
          g.beginPath();
          g.arc(x, y, r * (1 - k * 0.1), 0, Math.PI * 2);
          g.fill();
        }
        const [hx, hy] = strandAt(pts, pos);
        const glow = g.createRadialGradient(hx, hy, 0, hx, hy, r * 5);
        glow.addColorStop(0, hexA("#ffffff", a * 0.9));
        glow.addColorStop(0.3, hexA(col, a * 0.5));
        glow.addColorStop(1, hexA(col, 0));
        g.fillStyle = glow;
        g.beginPath();
        g.arc(hx, hy, r * 5, 0, Math.PI * 2);
        g.fill();
      };

      fiberState.forEach(({ f, st, dim, disabled, active, col }) => {
        if (st === "offline" || disabled || dim) return;
        // skill 05: memory fibers show a steady light
        // only — no continuous flow.
        if (kinds[f.to] === "memory") return;
        const speed = st === "awaiting" ? 0.16 : 0.34;
        f.strands.forEach((pts, i) => {
          if (i % 2) return;
          let pos = (t * speed + i * 0.21 + (f.to.length % 5) * 0.13) % 1;
          let a = active ? 1 : 0.75;
          let c = col;
          if (st === "awaiting" && pos > 0.62) {
            pos = 0.62;
            a *= 0.6 + Math.sin(t * 6) * 0.4;
            c = STATUS_COLOR.awaiting;
          }
          comet(pts, pos, c, 1.8, a);
        });
      });

      // selection bursts
      bursts.current = bursts.current.filter((b) => now - b.t0 < 1600);
      bursts.current.forEach((b) => {
        const pos = Math.min(1, (now - b.t0) / 1100);
        fiberState.forEach(({ f }) => {
          if (f.to !== b.id && !(b.id === coordinatorId && f.from === coordinatorId)) return;
          f.strands.forEach((pts) =>
            comet(pts, pos, "#e6fdff", 2.6, 1 - Math.max(0, (now - b.t0 - 1100) / 500))
          );
        });
      });

      // selected connection glow
      const selId = live.current.selectedConnection;
      if (selId) {
        fiberState.forEach(({ f, dim, col }) => {
          if (f.id !== selId || dim) return;
          f.strands.forEach((pts, i) => {
            const mid = i === Math.floor(f.strands.length / 2);
            stroke(pts, col, 0.16, mid ? 11 : 7);
          });
        });
      }

      // endpoint reconnection preview (dashed, with snap + validity)
      const it = interaction.current;
      if (it && it.kind === "endpoint-drag") {
        const fiber = L.fibers.find((f) => f.id === it.id);
        if (fiber) {
          const midStrand = fiber.strands[Math.floor(fiber.strands.length / 2)];
          const fixedPt = it.end === "to" ? strandAt(midStrand, 0) : strandAt(midStrand, 1);
          const dest =
            it.snapTarget && nodes[it.snapTarget]
              ? nodes[it.snapTarget]
              : { x: it.cursor.x, y: it.cursor.y };
          g.save();
          g.setLineDash([6, 6]);
          g.lineDashOffset = -t * 30;
          g.strokeStyle = it.snapTarget
            ? hexA(it.snapValid ? "#5ff0a8" : "#ff5c7a", 0.9)
            : hexA(SUN, 0.55);
          g.lineWidth = 1.6;
          g.beginPath();
          g.moveTo(fixedPt[0], fixedPt[1]);
          g.lineTo(dest.x, dest.y);
          g.stroke();
          g.restore();
          if (it.snapTarget) {
            ring(
              dest.x,
              dest.y,
              26,
              9,
              0.75,
              2,
              it.snapValid ? null : [4, 4],
              0,
              it.snapValid ? "#5ff0a8" : "#ff5c7a"
            );
          }
        }
        (it.validTargets || []).forEach((id) => {
          const n = nodes[id];
          if (n) ring(n.x, n.y, 27, 8, 0.3, 1.2, [4, 6], t * 12);
        });
      }

      // non-drag connect flow highlights
      if (live.current.connectFrom) {
        (live.current.connectTargets || []).forEach((id) => {
          const n = nodes[id];
          if (n) ring(n.x, n.y, 27, 8, 0.3, 1.2, [4, 6], -t * 12);
        });
        const sn = nodes[live.current.connectFrom];
        if (sn) ring(sn.x, sn.y, 34, 12, 0.5, 1.5, [8, 6], t * 16, MAG);
      }

      // memory retrieval pulses (skill 05): event-driven
      // one-shots — a request pulse agent -> memory, then
      // a result pulse memory -> agent. Never a flow.
      memPulses.current = memPulses.current.filter((p) => now - p.t0 < 1500);
      memPulses.current.forEach((p) => {
        const fiber = L.fibers.find((f) => f.from === p.from && f.to === p.to);
        if (!fiber) return;
        const midStrand = fiber.strands[Math.floor(fiber.strands.length / 2)];
        const progress = Math.min(1, (now - p.t0) / 900);
        if (p.phase === "request") {
          comet(midStrand, progress, "#e6fdff", 3, 1);
        } else {
          comet(midStrand, 1 - progress, p.ok ? "#5ff0a8" : "#ff5c7a", 3, 1);
        }
      });

      // node rings
      Object.entries(nodes).forEach(([id, n]) => {
        if (id === coordinatorId) return;
        const a = byId[id];
        if (!a) return;
        const col = STATUS_COLOR[a.status];
        const dimmed = dimNode(id);
        const sel = focus === id;
        const s = (n.child ? 0.7 : 1) * (sel ? 1.18 : 1);
        const k = dimmed ? 0.15 : a.status === "offline" ? 0.45 : 1;
        const pulse = a.status === "awaiting" ? 1 + Math.sin(t * 4) * 0.12 : 1;

        ring(n.x, n.y + 10 * s, 30 * s * pulse, 9 * s * pulse, 0.25 * k, 1, null, 0);

        g.save();
        g.strokeStyle = hexA(col, 0.75 * k);
        g.lineWidth = 2;
        g.setLineDash([14 * s, 8 * s]);
        g.lineDashOffset = t * (a.status === "offline" ? 0 : 20);
        g.beginPath();
        g.ellipse(n.x, n.y, 21 * s, 21 * s, 0, 0, Math.PI * 2);
        g.stroke();
        g.restore();

        g.strokeStyle = hexA(col, 0.4 * k);
        g.lineWidth = 1;
        g.beginPath();
        g.arc(n.x, n.y, 14 * s, 0, Math.PI * 2);
        g.stroke();

        const glow = g.createRadialGradient(n.x, n.y, 0, n.x, n.y, 26 * s);
        glow.addColorStop(0, hexA(col, 0.55 * k));
        glow.addColorStop(1, hexA(col, 0));
        g.fillStyle = glow;
        g.beginPath();
        g.arc(n.x, n.y, 26 * s, 0, Math.PI * 2);
        g.fill();
      });

      // rotating head point cloud
      const yaw = Math.sin(t * 0.22) * 0.5;
      const pitch = -0.08 + Math.sin(t * 0.17) * 0.04;
      const cy = Math.cos(yaw);
      const sy = Math.sin(yaw);
      const cp = Math.cos(pitch);
      const sp = Math.sin(pitch);
      const hx = C.x;
      const hy = C.y - R * 0.08;
      const scale = R * 0.98;
      const hermesSel = focus === coordinatorId;
      const fade = hermesDim ? 0.25 : 1;

      for (let i = 0, o = 0; i < head.length; i += 4, o += 3) {
        const x = head[i];
        const y = head[i + 1];
        const z = head[i + 2];
        const rx = x * cy + z * sy;
        const rz = -x * sy + z * cy;
        const ry = y * cp - rz * sp;
        const depth = y * sp + rz * cp;
        const breathe = 1 + Math.sin(t * 2 + y * 6) * 4e-3;
        proj[o] = hx + rx * scale * breathe;
        proj[o + 1] = hy - ry * scale;
        proj[o + 2] = depth;
      }

      [
        ["#1d6fb0", -2, -0.3, 0.35],
        ["#2fbfe8", -0.3, 0.25, 0.55],
        ["#8ff3ff", 0.25, 0.6, 0.75],
        ["#e8feff", 0.6, 2, 0.95],
      ].forEach(([col, lo, hi, a]) => {
        g.fillStyle = hexA(col, a * fade * (hermesSel ? 1 : 0.85));
        for (let i = 0, j = 0; i < proj.length; i += 3, j += 4) {
          const d = proj[i + 2];
          if (d < lo || d >= hi) continue;
          const sz = 0.9 + (d + 1) * 0.55 + (head[j + 3] > 0.97 ? 1.2 : 0);
          g.fillRect(proj[i] - sz / 2, proj[i + 1] - sz / 2, sz, sz);
        }
      });

      g.fillStyle = hexA("#5ff0a8", 0.35 * fade);
      for (let i = 0, j = 0; i < proj.length; i += 9, j += 12) {
        head[j + 1] > 0.55 && proj[i + 2] > 0 && g.fillRect(proj[i] - 1, proj[i + 1] - 1, 2, 2);
      }

      // contour lines around the head
      const contour = (col, base, amp, f1, f2, s1, s2, a) => {
        const pts = [];
        for (let i = 0; i <= 120; i++) {
          const th = (i / 120) * Math.PI * 2;
          const r =
            R *
            (base +
              amp * Math.sin(f1 * th + t * s1) +
              amp * 0.6 * Math.sin(f2 * th - t * s2) +
              bursting * 0.03 * Math.sin(th * 9 + t * 10));
          pts.push(hx + Math.cos(th) * r * 0.86, hy + Math.sin(th) * r * 1.06);
        }
        [
          [7, 0.06],
          [3, 0.16],
          [1.3, 0.85],
        ].forEach(([lw, k]) => {
          g.strokeStyle = hexA(col, a * k * fade);
          g.lineWidth = lw;
          g.beginPath();
          g.moveTo(pts[0], pts[1]);
          for (let i = 2; i < pts.length; i += 2) g.lineTo(pts[i], pts[i + 1]);
          g.stroke();
        });
      };
      contour("#5ff3ff", 1.12, 0.06, 5, 3, 0.9, 0.6, hermesSel ? 1 : 0.75);
      contour("#5ff0a8", 1.18, 0.05, 4, 7, -0.7, 0.8, 0.5);
      contour(MAG, 1.07, 0.045, 6, 2, 0.5, -1.1, 0.4);

      // speech waveform
      const wave = (col, cx, half, amp, freq, speed, a) => {
        [
          [5, 0.12],
          [1.6, 0.95],
        ].forEach(([lw, k]) => {
          g.strokeStyle = hexA(col, a * k * fade);
          g.lineWidth = lw;
          g.beginPath();
          for (let i = 0; i <= 90; i++) {
            const u = (i / 90) * 2 - 1;
            const x = cx + u * half;
            const y = hy + R * 0.12 + Math.sin(u * freq + t * speed) * amp * Math.exp(-u * u * 3.2);
            i ? g.lineTo(x, y) : g.moveTo(x, y);
          }
          g.stroke();
        });
      };
      const amp = R * (0.16 + bursting * 0.12 + Math.max(0, Math.sin(t * 1.3)) ** 6 * 0.08);
      wave("#bff8ff", hx - R * 0.12, R * 0.42, amp, 26, 9, 1);
      wave(MAG, hx + R * 0.3, R * 0.22, amp * 0.6, 22, -7, 0.85);

      raf = requestAnimationFrame(frame);
    };

    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [size, head]);

  const { nodes, C, R } = layout;

  // ---- Pointer helpers (canvas pixel coordinates) ----

  const canvasPos = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const cancelInteraction = () => {
    interaction.current = null;
  };

  // Node dragging — edit mode only, coordinator fixed, locked nodes stay.
  const onNodePointerDown = (e, id) => {
    if (e.button !== 0 || mode !== "edit") return;
    if (interaction.current) return; // a fiber interaction owns the pointer
    if (id === coordinatorId || kinds[id] === "orchestrator") return;
    if (view.positions[id]?.locked) return;
    const node = layout.nodes[id];
    if (!node) return;
    const pos = canvasPos(e);
    interaction.current = {
      kind: "node-drag",
      id,
      startX: pos.x,
      startY: pos.y,
      origX: node.x,
      origY: node.y,
      moved: false,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onNodePointerMove = (e, id) => {
    const it = interaction.current;
    if (!it || it.kind !== "node-drag" || it.id !== id) return;
    const pos = canvasPos(e);
    if (!it.moved && Math.hypot(pos.x - it.startX, pos.y - it.startY) > 4) it.moved = true;
    if (!it.moved) return;
    const clamped = clampPosition(
      { x: it.origX + pos.x - it.startX, y: it.origY + pos.y - it.startY },
      size.W,
      size.H
    );
    onViewChange((prev) => setPosition(prev, id, clamped.x, clamped.y));
  };

  const onNodePointerUp = (e, id) => {
    const it = interaction.current;
    if (!it || it.kind !== "node-drag" || it.id !== id) return;
    interaction.current = null;
    if (it.moved) {
      suppressClick.current = true; // a drag is not a click
      onViewSnapshot();
    }
  };

  // Connection selection — hit area wider than the visible fiber.
  const onCanvasPointerDown = (e) => {
    if (e.button !== 0) return;
    const hit = nearestStrand(layout.fibers, canvasPos(e), 14);
    if (hit) {
      setSelectedConnection(hit.fiber.id);
    } else {
      setSelectedConnection(null);
    }
  };

  // Curvature handle — view-only geometry.
  const onMidPointerDown = (e) => {
    if (e.button !== 0 || mode !== "edit" || !selectedConnection) return;
    if (interaction.current) return;
    interaction.current = { kind: "curve-drag", id: selectedConnection, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onMidPointerMove = (e) => {
    const it = interaction.current;
    if (!it || it.kind !== "curve-drag") return;
    it.moved = true;
    const world = screenToWorld(view, canvasPos(e));
    onViewChange((prev) => setFiberMidpoint(prev, it.id, world));
  };

  const onMidPointerUp = () => {
    const it = interaction.current;
    if (it && it.kind === "curve-drag") {
      interaction.current = null;
      if (it.moved) onViewSnapshot();
    }
  };

  // Endpoint reconnection — draft topology change.
  const computeEndpointState = (drag, pos) => {
    const fiber = connections.find((c) => c.id === drag.id);
    if (!fiber) {
      return { cursor: pos, snapTarget: null, snapValid: false, validTargets: [], fixedId: null };
    }
    const others = connections.filter((c) => c.id !== drag.id);
    const fixedId = drag.end === "to" ? fiber.from : fiber.to;
    const validTargets = [];
    for (const a of agents) {
      if (a.id === fixedId) continue;
      const spec = drag.end === "to" ? { from: fixedId, to: a.id } : { from: a.id, to: fixedId };
      if (compatibleTypes(registry, others, spec).length > 0) validTargets.push(a.id);
    }
    let snapTarget = null;
    let snapValid = false;
    let best = 48;
    for (const a of agents) {
      const n = layout.nodes[a.id];
      if (!n) continue;
      const d = Math.hypot(pos.x - n.x, pos.y - n.y);
      if (d < best) {
        best = d;
        snapTarget = a.id;
        snapValid = validTargets.includes(a.id);
      }
    }
    return { cursor: pos, snapTarget, snapValid, validTargets, fixedId };
  };

  const onEndPointerDown = (e, end) => {
    if (e.button !== 0 || mode !== "edit" || !selectedConnection) return;
    if (interaction.current) return;
    interaction.current = {
      kind: "endpoint-drag",
      id: selectedConnection,
      end,
      cursor: canvasPos(e),
      snapTarget: null,
      snapValid: false,
      validTargets: [],
      fixedId: null,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onEndPointerMove = (e) => {
    const it = interaction.current;
    if (!it || it.kind !== "endpoint-drag") return;
    interaction.current = { ...it, ...computeEndpointState(it, canvasPos(e)) };
  };

  const onEndPointerUp = (e) => {
    const it = interaction.current;
    if (!it || it.kind !== "endpoint-drag") return;
    interaction.current = null;
    const { snapTarget, snapValid, fixedId } = computeEndpointState(it, canvasPos(e));
    // Dropping on empty space (or an invalid target) cancels by
    // default — the previous connection is preserved untouched.
    if (!snapTarget || !snapValid || !fixedId) return;
    const spec =
      it.end === "to" ? { from: fixedId, to: snapTarget } : { from: snapTarget, to: fixedId };
    const types = compatibleTypes(
      registry,
      connections.filter((c) => c.id !== it.id),
      spec
    );
    if (types.length === 0) return;
    if (types.length === 1) {
      onProposeConnection({ ...spec, type: types[0] });
    } else {
      setPicker({
        from: spec.from,
        to: spec.to,
        types: types.map((type) => ({ type, label: strings.types[type] })),
        x: canvasPos(e).x + 12,
        y: canvasPos(e).y - 10,
      });
    }
  };

  // Non-drag connect flow: a node was chosen as source, now a
  // target node was clicked — offer the compatible types.
  const openPickerAt = (fromId, toId) => {
    const types = compatibleTypes(registry, connections, { from: fromId, to: toId });
    if (types.length === 0) {
      flash(false, toId, strings.noTypes);
      return;
    }
    const node = layout.nodes[toId];
    setPicker({
      from: fromId,
      to: toId,
      types: types.map((type) => ({ type, label: strings.types[type] })),
      x: (node ? node.x : size.W / 2) + 36,
      y: (node ? node.y : size.H / 2) - 30,
    });
  };

  const confirmPicker = (type) => {
    if (!picker) return;
    onProposeConnection({ from: picker.from, to: picker.to, type });
    setPicker(null);
    setConnectFrom(null);
  };

  const cancelPicker = () => {
    setPicker(null);
    setConnectFrom(null);
  };

  return (
    <div
      ref={wrapRef}
      className="absolute inset-0"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          setSelected(null);
          setSelectedConnection(null);
          setConnectFrom(null);
        } else if (e.target === canvasRef.current) {
          setSelected(null);
          setConnectFrom(null);
        }
      }}
    >
      <canvas
        ref={canvasRef}
        className="absolute inset-0"
        onPointerDown={onCanvasPointerDown}
      />
      <button
        aria-label="Hermes"
        onClick={() => setSelected(coordinatorId)}
        onMouseEnter={() => setHover(coordinatorId)}
        onMouseLeave={() => setHover(null)}
        className="absolute rounded-full"
        style={{ left: C.x - R * 0.85, top: C.y - R * 1.1, width: R * 1.7, height: R * 2.1 }}
      />
      <div
        className="core-tag pointer-events-none absolute -translate-x-1/2"
        style={{
          left: C.x,
          top: C.y + R * 1.62,
          opacity: q && !match(byId[coordinatorId]) ? 0.3 : 1,
        }}
      >
        {coreLabel}
      </div>
      {agents
        .filter((a) => a.id !== coordinatorId && nodes[a.id])
        .map((a) => {
          const n = nodes[a.id];
          const left = n.side < 0;
          const dim = dimNode(a.id);
          const locked = view.positions[a.id]?.locked;
          const draggable =
            mode === "edit" && a.id !== coordinatorId && kinds[a.id] !== "orchestrator" && !locked;
          return (
            <div key={a.id}>
              <button
                type="button"
                aria-label={a.name}
                title={locked ? strings.locked : undefined}
                onClick={() => {
                  if (suppressClick.current) {
                    suppressClick.current = false;
                    return;
                  }
                  if (connectFrom && connectFrom !== a.id) {
                    openPickerAt(connectFrom, a.id);
                    return;
                  }
                  setSelected(a.id);
                }}
                onPointerDown={(e) => onNodePointerDown(e, a.id)}
                onPointerMove={(e) => onNodePointerMove(e, a.id)}
                onPointerUp={(e) => onNodePointerUp(e, a.id)}
                onPointerCancel={cancelInteraction}
                onLostPointerCapture={cancelInteraction}
                className="absolute rounded-full"
                style={{
                  left: n.x - 26,
                  top: n.y - 26,
                  width: 52,
                  height: 52,
                  cursor: draggable ? "grab" : "default",
                }}
              />
              {size.W >= 640 && kinds[a.id] !== "memory" && (
                <div
                  className="cmd-tag mono pointer-events-none absolute"
                  dir="ltr"
                  style={{
                    bottom: size.H - n.y + 30,
                    [left ? "left" : "right"]: left ? n.x - 18 : size.W - n.x - 18,
                    textAlign: left ? "left" : "right",
                    color: STATUS_COLOR[a.status],
                    opacity: dim ? 0.2 : 0.9,
                  }}
                >
                  {(() => {
                    const [cmd, state] = cmdFor(a);
                    return (
                      <>
                        {state && <span className="block opacity-70">{state}</span>}
                        {cmd}
                      </>
                    );
                  })()}
                </div>
              )}
              <div
                className="node-label pointer-events-none absolute"
                dir={rtl ? "rtl" : "ltr"}
                style={{
                  top: n.y + 28,
                  [left ? "left" : "right"]: left ? Math.max(6, n.x - 30) : Math.max(6, size.W - n.x - 30),
                  textAlign: left ? "left" : "right",
                  opacity: dim ? 0.25 : 1,
                }}
              >
                {labelFor(a)}
              </div>
            </div>
          );
        })}

      {/* Subagent clusters (skill 06): a collapsed badge on
          the parent node, or expanded satellite nodes around
          it. Runtime nodes stay visually subordinate to the
          central hologram — smaller, dimmer, thinner. */}
      {clusters.map((cl) => {
        const parent = nodes[cl.agentId];
        if (!parent) return null;
        const expanded = expandedClusters.has(cl.agentId);
        const sats = expanded
          ? (subtrees[cl.agentId] || []).filter((r) => r.depth >= 1)
          : [];
        return (
          <div key={cl.agentId}>
            {expanded && sats.length > 0 && (
              <svg className="pointer-events-none absolute inset-0 h-full w-full">
                {sats.map((s) => {
                  const pos = satellitePos(parent, sats, s);
                  return (
                    <line
                      key={s.run.runId}
                      x1={parent.x}
                      y1={parent.y}
                      x2={pos.x}
                      y2={pos.y}
                      stroke={s.depth > 1 ? "#3a5a78" : "#4a7a9a"}
                      strokeWidth={s.depth > 1 ? 1 : 1.4}
                      strokeDasharray="3 4"
                      opacity={0.7}
                    />
                  );
                })}
              </svg>
            )}
            {!expanded && (
              <button
                type="button"
                onClick={() => onToggleCluster(cl.agentId)}
                className="cluster-badge absolute z-20 -translate-x-1/2"
                style={{ left: parent.x, top: parent.y + 64 }}
                dir={rtl ? "rtl" : "ltr"}
              >
                <i className="dotlive h-1.5 w-1.5 rounded-full bg-[var(--sun)] text-[var(--sun)]" />
                <span>
                  {cl.counts.active} {strings.activeSubagents}
                </span>
                {cl.counts.waiting > 0 && (
                  <span className="opacity-80">
                    {" "}
                    · {cl.counts.waiting} {strings.waitingShort}
                  </span>
                )}
                {cl.counts.failed > 0 && (
                  <span className="text-[#ff5c7a]">
                    {" "}
                    · {cl.counts.failed} {strings.failedShort}
                  </span>
                )}
                {cl.freshness === "stale" && (
                  <span className="mock-tag !text-[10px]">STALE</span>
                )}
              </button>
            )}
            {expanded &&
              sats.map((s) => {
                const pos = satellitePos(parent, sats, s);
                const on = selectedRun === s.run.runId;
                const col = RUN_STATE_COLOR[s.run.state] || "#6b7fa6";
                const agent = agents.find((a) => a.id === s.run.agentId);
                return (
                  <button
                    key={s.run.runId}
                    type="button"
                    onClick={() => onSelectRun(s.run.runId)}
                    className="cluster-node absolute z-20 -translate-x-1/2 -translate-y-1/2"
                    style={{ left: pos.x, top: pos.y }}
                    dir={rtl ? "rtl" : "ltr"}
                  >
                    <span
                      className="flex items-center gap-1.5 rounded-lg border bg-[rgba(2,10,20,.88)] px-2 py-1"
                      style={{
                        borderColor: on ? "var(--sun)" : "rgba(74,122,154,.4)",
                        boxShadow: on ? "0 0 14px -2px #38e8ff88" : undefined,
                      }}
                    >
                      <i
                        className="h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ background: col }}
                      />
                      <span className="text-[11px] font-medium">
                        {agent ? agent.name : s.run.agentId}
                      </span>
                      {s.run.assignedTask && (
                        <span className="max-w-[90px] truncate text-[10px] text-[var(--mu)]">
                          {s.run.assignedTask}
                        </span>
                      )}
                      <span className="shrink-0 text-[10px]" style={{ color: col }}>
                        {strings.runStates[s.run.state]}
                      </span>
                      <span className="mono shrink-0 text-[10px] text-[var(--mu)]">
                        {formatElapsed(s.run)}
                      </span>
                    </span>
                  </button>
                );
              })}
            {expanded && (
              <button
                type="button"
                onClick={() => onToggleCluster(cl.agentId)}
                className="cluster-badge absolute z-20 -translate-x-1/2"
                style={{ left: parent.x, top: parent.y + 64 }}
              >
                {strings.collapse}
              </button>
            )}
          </div>
        );
      })}

      {/* Connection editing handles (edit mode, selected connection) */}
      {mode === "edit" &&
        selectedConnection &&
        (() => {
          const fiber = layout.fibers.find((f) => f.id === selectedConnection);
          if (!fiber) return null;
          const midStrand = fiber.strands[Math.floor(fiber.strands.length / 2)];
          const pFrom = strandAt(midStrand, 0);
          const pTo = strandAt(midStrand, 1);
          const mid = strandMidpoint(fiber.strands);
          const endHandle = (end, pt) => (
            <button
              key={end}
              type="button"
              aria-label={`${strings.endpoint}: ${end}`}
              title={strings.dropHint}
              onPointerDown={(e) => onEndPointerDown(e, end)}
              onPointerMove={onEndPointerMove}
              onPointerUp={onEndPointerUp}
              onPointerCancel={cancelInteraction}
              onLostPointerCapture={cancelInteraction}
              className="absolute z-20 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--sun)] bg-[#03121c]"
              style={{
                left: pt[0],
                top: pt[1],
                cursor: "crosshair",
                boxShadow: "0 0 10px #38e8ff",
              }}
            />
          );
          return (
            <>
              <button
                type="button"
                aria-label={strings.curvature}
                title={strings.curvature}
                onPointerDown={onMidPointerDown}
                onPointerMove={onMidPointerMove}
                onPointerUp={onMidPointerUp}
                onPointerCancel={cancelInteraction}
                onLostPointerCapture={cancelInteraction}
                className="absolute z-20 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[4px] border border-[var(--sun)] bg-[#03121c]"
                style={{
                  left: mid[0],
                  top: mid[1],
                  cursor: "move",
                  boxShadow: "0 0 10px #38e8ff",
                }}
              />
              {endHandle("from", pFrom)}
              {endHandle("to", pTo)}
              <button
                type="button"
                onClick={() => onDisconnectConnection(selectedConnection)}
                className="glass absolute z-20 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] text-[#ffc0ca] transition hover:bg-[rgba(255,92,122,.12)]"
                style={{ left: mid[0], top: mid[1] + 22, transform: "translateX(-50%)" }}
              >
                <Scissors size={13} />
                {strings.disconnect}
              </button>
            </>
          );
        })()}

      {/* Connection type picker */}
      {picker && (
        <div
          className="absolute z-40"
          style={{
            left: Math.min(Math.max(8, picker.x), Math.max(8, size.W - 240)),
            top: Math.min(Math.max(8, picker.y), Math.max(8, size.H - 220)),
          }}
        >
          <ConnectionPicker
            t={strings}
            title={`${strings.connectTo} ${byId[picker.to]?.name || picker.to}`}
            types={picker.types}
            onConfirm={confirmPicker}
            onCancel={cancelPicker}
          />
        </div>
      )}

      {/* Non-drag connect flow hint */}
      {connectFrom && (
        <div className="glass rise absolute bottom-3 start-3 z-30 px-3 py-2 text-[13px] text-[var(--sun2)]">
          {strings.connectHint}
        </div>
      )}
    </div>
  );
}
