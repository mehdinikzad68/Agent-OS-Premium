// Point-cloud head (minified name in bundle: lx).
// Layout of the returned Float32Array: [x, y, z, sparkle] per point.
// 3600 head points + 420 neck/base points.

export function buildHead(count = 3600, rand = Math.random) {
  const pts = [];
  const g = (v, s) => Math.exp(-(v * v) / s);

  for (let i = 0; i < count; i++) {
    const banded = i % 5 < 2;
    const theta = rand() * Math.PI * 2;
    const y0 = banded ? Math.round((rand() * 2 - 1) * 13) / 13 : rand() * 2 - 1;
    const r = Math.sqrt(Math.max(0, 1 - y0 * y0));
    let x = r * Math.cos(theta);
    const y = y0;
    let z = r * Math.sin(theta);

    x *= 0.74;
    z *= 0.86;

    // jaw taper
    if (y < -0.05) {
      const k = 1 - 0.42 * Math.pow((-0.05 - y) / 0.95, 1.3);
      x *= k;
      z *= 1 - 0.18 * ((-0.05 - y) / 0.95);
    }

    // back of skull
    if (y > 0.35) z -= 0.06 * (y - 0.35);

    // face features (front half only)
    if (z > 0.1) {
      z += 0.2 * g(x, 6e-3) * g(y + 0.08, 0.05); // nose
      z += 0.07 * g(y - 0.26, 4e-3) * (Math.abs(x) < 0.5); // brow
      z -= 0.1 * g(Math.abs(x) - 0.25, 8e-3) * g(y - 0.13, 6e-3); // eye sockets
      z += 0.045 * g(x, 0.03) * g(y + 0.44, 3e-3); // lips
      z += 0.06 * g(x, 0.02) * g(y + 0.66, 0.012); // chin
    }

    // ears
    if (Math.abs(z) < 0.15 && Math.abs(y - 0.02) < 0.2) {
      x += Math.sign(x) * 0.06 * g(y - 0.02, 0.01);
    }

    pts.push(x, y, z, rand());
  }

  // neck / base
  for (let i = 0; i < 420; i++) {
    const theta = rand() * Math.PI * 2;
    const y = -0.82 - rand() * 0.42;
    const r = 0.3 + (y + 0.82) * -0.25;
    pts.push(Math.cos(theta) * r, y, Math.sin(theta) * r * 0.9, rand());
  }

  return new Float32Array(pts);
}
