// Node placement and fiber strands (minified names in bundle: ux, Ms, _c).
//
// Extended for interactive editing:
// - manual view positions override the automatic placement
// - fiber curvature control points (view-only geometry)
// - pure hit-testing helpers for pointer interaction
// All geometry is direction-agnostic: RTL and LTR behave identically.

const MARGIN = 44; // keeps labels and command tags reachable

const isNum = (n) => typeof n === "number" && Number.isFinite(n);

// Ms: sample a cubic Bezier into a flat [x0, y0, x1, y1, ...] array.
export const bez = (p0, p1, p2, p3, steps = 48) => {
  const out = new Float32Array((steps + 1) * 2);
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const u = 1 - t;
    out[i * 2] = u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x;
    out[i * 2 + 1] = u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y;
  }
  return out;
};

// Sample a cubic Bezier whose midpoint (t=0.5) passes through
// `midpoint`. Both control points are shifted by 4/3 of the midpoint
// delta, so the middle strand lands exactly on the requested point
// while the rest of the bundle bends along with it. View-only.
export const bezWithMidpoint = (p0, p1, p2, p3, midpoint, steps = 48) => {
  if (!midpoint || !isNum(midpoint.x) || !isNum(midpoint.y)) {
    return bez(p0, p1, p2, p3, steps);
  }
  const mx = (p0.x + 3 * p1.x + 3 * p2.x + p3.x) / 8;
  const my = (p0.y + 3 * p1.y + 3 * p2.y + p3.y) / 8;
  const dx = ((midpoint.x - mx) * 4) / 3;
  const dy = ((midpoint.y - my) * 4) / 3;
  return bez(
    p0,
    { x: p1.x + dx, y: p1.y + dy },
    { x: p2.x + dx, y: p2.y + dy },
    p3,
    steps
  );
};

// _c: point at normalized position t (0..1) along a sampled polyline.
export const strandAt = (pts, t) => {
  const last = pts.length / 2 - 1;
  const f = Math.max(0, Math.min(last, t * last));
  const i = Math.floor(f);
  const k = f - i;
  const j = Math.min(last, i + 1);
  return [pts[i * 2] + (pts[j * 2] - pts[i * 2]) * k, pts[i * 2 + 1] + (pts[j * 2 + 1] - pts[i * 2 + 1]) * k];
};

// Midpoint of a fiber bundle: the middle strand at t=0.5.
export const strandMidpoint = (strands) =>
  strandAt(strands[Math.floor(strands.length / 2)], 0.5);

// Clamp a world position into the canvas so nodes and their labels
// never become unreachable after dragging or resizing.
export const clampPosition = (p, W, H, margin = MARGIN) => ({
  x: Math.min(Math.max(margin, p.x), Math.max(margin, W - margin)),
  y: Math.min(Math.max(margin, p.y), Math.max(margin, H - margin)),
});

// Distance from a point to a line segment.
function pointToSegmentDistance(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}

// Hit-testing: the closest strand within `threshold` pixels. The hit
// area is deliberately wider than the visible fiber (1-3.5 px).
export const nearestStrand = (fibers, point, threshold = 14) => {
  let best = null;
  for (const f of fibers) {
    for (const pts of f.strands) {
      for (let i = 2; i < pts.length; i += 2) {
        const d = pointToSegmentDistance(
          point.x,
          point.y,
          pts[i - 2],
          pts[i - 1],
          pts[i],
          pts[i + 1]
        );
        if (!best || d < best.distance) {
          best = { distance: d, fiber: f };
        }
      }
    }
  }
  return best && best.distance <= threshold ? best : null;
};

// ux
export function computeLayout(
  agents,
  links,
  W,
  H,
  positions = {},
  fiberGeometry = {},
  coordinatorId = "hermes"
) {
  const C = { x: W / 2, y: H * 0.47 };
  const R = Math.max(70, Math.min(W * 0.15, H * 0.25));
  const byId = Object.fromEntries(agents.map((a) => [a.id, a]));

  // top-level tools, each followed by its relay children
  const groups = agents
    .filter((a) => a.id !== coordinatorId && !a.parent)
    .map((a) => [a, ...agents.filter((c) => c.parent === a.id)]);

  const sides = { L: [], R: [] };
  groups.forEach((g) => {
    (sides.L.length <= sides.R.length ? sides.L : sides.R).push(...g);
  });

  const nodes = {};
  const narrow = W < 640;
  ["L", "R"].forEach((s) => {
    const list = sides[s];
    const n = list.length;
    list.forEach((a, i) => {
      const y = H * (0.13 + 0.68 * (n === 1 ? 0.5 : i / (n - 1)));
      const k = (y - C.y) / (H * 0.4);
      const inset = (narrow ? 34 : W * 0.075) + k * k * W * (narrow ? 0.03 : 0.085);
      const base = {
        x: s === "L" ? inset : W - inset,
        y,
        side: s === "L" ? -1 : 1,
        child: !!a.parent,
      };
      // Manual view positions override the automatic placement.
      const manual = positions[a.id];
      if (manual && isNum(manual.x) && isNum(manual.y)) {
        const clamped = clampPosition(manual, W, H);
        nodes[a.id] = { ...base, x: clamped.x, y: clamped.y };
      } else {
        nodes[a.id] = base;
      }
    });
  });
  nodes[coordinatorId] = { x: C.x, y: C.y, side: 0 };

  const fibers = links
    .map((l) => {
      const a = nodes[l.from];
      const b = nodes[l.to];
      if (!a || !b || !byId[l.from] || !byId[l.to]) return null;

      const geo = fiberGeometry[l.id];
      const mid =
        geo && isNum(geo.midpoint?.x) && isNum(geo.midpoint?.y)
          ? geo.midpoint
          : null;

      const strands = [];
      if (l.from === coordinatorId) {
        const side = b.side;
        const count = b.child ? 3 : 7;
        for (let i = 0; i < count; i++) {
          const o = i - (count - 1) / 2;
          const start = {
            x: C.x + side * R * 0.62,
            y: C.y + (b.y - C.y) * 0.22 + o * R * 0.045,
          };
          strands.push(
            bezWithMidpoint(
              start,
              {
                x: C.x + side * R * 1.55,
                y: start.y + o * R * 0.13 + (b.y - C.y) * 0.08,
              },
              {
                x: b.x - side * Math.max(60, Math.abs(b.x - C.x) * 0.45),
                y: b.y + o * 2.4,
              },
              { x: b.x - side * 20, y: b.y + o * 0.6 },
              mid
            )
          );
        }
      } else {
        const sameSide = a.side === b.side;
        for (let i = 0; i < 3; i++) {
          const o = (i - 1) * 3;
          if (sameSide) {
            const bow = -a.side * (40 + Math.abs(a.y - b.y) * 0.25);
            strands.push(
              bezWithMidpoint(
                { x: a.x, y: a.y + 14 },
                { x: a.x + bow + o, y: a.y + 40 },
                { x: b.x + bow + o, y: b.y - 40 },
                { x: b.x, y: b.y - 14 },
                mid
              )
            );
          } else {
            const floor = H * 0.95 + o;
            strands.push(
              bezWithMidpoint(
                { x: a.x, y: a.y + 14 },
                { x: a.x, y: floor },
                { x: b.x, y: floor },
                { x: b.x, y: b.y + 14 },
                mid
              )
            );
          }
        }
      }
      return { ...l, strands, relay: l.from !== coordinatorId };
    })
    .filter(Boolean);

  return { C, R, nodes, fibers };
}
