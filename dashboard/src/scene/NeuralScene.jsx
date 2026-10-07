// Canvas 2D scene + HTML overlay labels (minified name in bundle: As).
import { useEffect, useMemo, useRef, useState } from "react";
import { STATUS_COLOR, SUN, MAG, hexA } from "./colors.js";
import { buildHead } from "./head.js";
import { computeLayout, strandAt } from "./layout.js";
import { paintBackdrop } from "./backdrop.js";
import { mulberry32 } from "./random.js";
import { cmdFor } from "../data.js";

/**
 * Optional (not in the original):
 *   seed       number  -> head + backdrop use Mulberry32(seed) instead of Math.random
 *   frozenTime number  -> scene clock pinned to this many seconds (animation stops)
 * Without them the scene behaves exactly like the original bundle.
 */
export default function NeuralScene({
  agents,
  links,
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
}) {
  const wrapRef = useRef();
  const canvasRef = useRef();
  const [size, setSize] = useState({ W: 800, H: 520 });
  const [hover, setHover] = useState(null);
  const head = useMemo(() => buildHead(3600, seed == null ? Math.random : mulberry32(seed)), [seed]);

  useEffect(() => {
    const ro = new ResizeObserver(([entry]) => {
      const r = entry.contentRect;
      setSize({ W: Math.max(300, r.width), H: Math.max(380, r.height) });
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(() => computeLayout(agents, links, size.W, size.H), [agents, links, size]);
  const byId = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);
  const q = query.trim().toLowerCase();
  const match = (a) => !q || a.name.toLowerCase().includes(q) || a.id.includes(q);
  const focus = selected || highlight || hover;
  const linked = (id) => links.some((l) => (l.from === focus && l.to === id) || (l.to === focus && l.from === id));
  const dimNode = (id) => (q && !match(byId[id])) || (focus && focus !== id && focus !== "hermes" && id !== "hermes" && !linked(id));

  // latest render values for the draw loop
  const live = useRef({});
  live.current = { L: layout, byId, focus, p: q, match, dimNode };

  // burst comets fired on selection
  const bursts = useRef([]);
  useEffect(() => {
    burst?.id && bursts.current.push({ id: burst.id, t0: performance.now() });
  }, [burst]);

  // keep the latest frozenTime visible to the loop without restarting it
  const frozen = useRef(frozenTime);
  frozen.current = frozenTime;

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

      const hermesDim = q && !match(byId.hermes);
      const bursting = bursts.current.length ? 1 : 0;

      const ring = (x, y, rx, ry, a, lw, dash, off) => {
        g.save();
        g.strokeStyle = hexA(SUN, a);
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
        const st = to.status === "running" && from.status !== "running" && from.id !== "hermes" ? from.status : to.status;
        const active = focus && (f.from === focus || f.to === focus);
        const dim = (focus && !active) || (q && !(match(from) || match(to)));
        return { f, st, active, dim, col: STATUS_COLOR[st] };
      });

      fiberState.forEach(({ f, st, active, dim, col }) => {
        const off = st === "offline";
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

      fiberState.forEach(({ f, st, dim, active, col }) => {
        if (st === "offline" || dim) return;
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
          if (f.to !== b.id && !(b.id === "hermes" && f.from === "hermes")) return;
          f.strands.forEach((pts) => comet(pts, pos, "#e6fdff", 2.6, 1 - Math.max(0, (now - b.t0 - 1100) / 500)));
        });
      });

      // node rings
      Object.entries(nodes).forEach(([id, n]) => {
        if (id === "hermes") return;
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
      const hermesSel = focus === "hermes";
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
          const r = R * (base + amp * Math.sin(f1 * th + t * s1) + amp * 0.6 * Math.sin(f2 * th - t * s2) + bursting * 0.03 * Math.sin(th * 9 + t * 10));
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

  return (
    <div
      ref={wrapRef}
      className="absolute inset-0"
      onClick={(e) => {
        (e.target === e.currentTarget || e.target === canvasRef.current) && setSelected(null);
      }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />
      <button
        aria-label="Hermes"
        onClick={() => setSelected("hermes")}
        onMouseEnter={() => setHover("hermes")}
        onMouseLeave={() => setHover(null)}
        className="absolute rounded-full"
        style={{ left: C.x - R * 0.85, top: C.y - R * 1.1, width: R * 1.7, height: R * 2.1 }}
      />
      <div
        className="core-tag pointer-events-none absolute -translate-x-1/2"
        style={{ left: C.x, top: C.y + R * 1.62, opacity: q && !match(byId.hermes) ? 0.3 : 1 }}
      >
        {coreLabel}
      </div>
      {agents
        .filter((a) => a.id !== "hermes" && nodes[a.id])
        .map((a) => {
          const n = nodes[a.id];
          const left = n.side < 0;
          const dim = dimNode(a.id);
          return (
            <div key={a.id}>
              <button
                aria-label={a.name}
                onClick={() => setSelected(a.id)}
                onMouseEnter={() => setHover(a.id)}
                onMouseLeave={() => setHover(null)}
                className="absolute rounded-full"
                style={{ left: n.x - 26, top: n.y - 26, width: 52, height: 52 }}
              />
              {size.W >= 640 && (
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
    </div>
  );
}
