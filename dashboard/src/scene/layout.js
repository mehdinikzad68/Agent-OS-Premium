// Node placement and fiber strands (minified names in bundle: ux, Ms, _c).

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

// _c: point at normalized position t (0..1) along a sampled polyline.
export const strandAt = (pts, t) => {
  const last = pts.length / 2 - 1;
  const f = Math.max(0, Math.min(last, t * last));
  const i = Math.floor(f);
  const k = f - i;
  const j = Math.min(last, i + 1);
  return [pts[i * 2] + (pts[j * 2] - pts[i * 2]) * k, pts[i * 2 + 1] + (pts[j * 2 + 1] - pts[i * 2 + 1]) * k];
};

// ux
export function computeLayout(agents, links, W, H) {
  const C = { x: W / 2, y: H * 0.47 };
  const R = Math.max(70, Math.min(W * 0.15, H * 0.25));
  const byId = Object.fromEntries(agents.map((a) => [a.id, a]));

  // top-level tools, each followed by its relay children
  const groups = agents
    .filter((a) => a.id !== "hermes" && !a.parent)
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
      nodes[a.id] = { x: s === "L" ? inset : W - inset, y, side: s === "L" ? -1 : 1, child: !!a.parent };
    });
  });
  nodes.hermes = { x: C.x, y: C.y, side: 0 };

  const fibers = links
    .map((l) => {
      const a = nodes[l.from];
      const b = nodes[l.to];
      if (!a || !b || !byId[l.from] || !byId[l.to]) return null;

      const strands = [];
      if (l.from === "hermes") {
        const side = b.side;
        const count = b.child ? 3 : 7;
        for (let i = 0; i < count; i++) {
          const o = i - (count - 1) / 2;
          const start = { x: C.x + side * R * 0.62, y: C.y + (b.y - C.y) * 0.22 + o * R * 0.045 };
          strands.push(
            bez(
              start,
              { x: C.x + side * R * 1.55, y: start.y + o * R * 0.13 + (b.y - C.y) * 0.08 },
              { x: b.x - side * Math.max(60, Math.abs(b.x - C.x) * 0.45), y: b.y + o * 2.4 },
              { x: b.x - side * 20, y: b.y + o * 0.6 }
            )
          );
        }
      } else {
        const sameSide = a.side === b.side;
        for (let i = 0; i < 3; i++) {
          const o = (i - 1) * 3;
          if (sameSide) {
            const bow = -a.side * (40 + Math.abs(a.y - b.y) * 0.25);
            strands.push(bez({ x: a.x, y: a.y + 14 }, { x: a.x + bow + o, y: a.y + 40 }, { x: b.x + bow + o, y: b.y - 40 }, { x: b.x, y: b.y - 14 }));
          } else {
            const floor = H * 0.95 + o;
            strands.push(bez({ x: a.x, y: a.y + 14 }, { x: a.x, y: floor }, { x: b.x, y: floor }, { x: b.x, y: b.y + 14 }));
          }
        }
      }
      return { ...l, strands, relay: l.from !== "hermes" };
    })
    .filter(Boolean);

  return { C, R, nodes, fibers };
}
