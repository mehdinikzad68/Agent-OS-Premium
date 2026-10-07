// Offscreen backdrop: radial base, blurred "city light" rectangles, 32px grid, vignette.
// Minified name in bundle: nx.

export function paintBackdrop(W, H, dpr, rand = Math.random) {
  const cv = document.createElement("canvas");
  cv.width = W * dpr;
  cv.height = H * dpr;
  const g = cv.getContext("2d");
  g.scale(dpr, dpr);

  const base = g.createRadialGradient(W / 2, H * 0.47, 0, W / 2, H * 0.47, Math.max(W, H) * 0.75);
  base.addColorStop(0, "#0a2236");
  base.addColorStop(0.5, "#061423");
  base.addColorStop(1, "#02070f");
  g.fillStyle = base;
  g.fillRect(0, 0, W, H);

  g.filter = "blur(2.5px)";
  for (let i = 0; i < 170; i++) {
    const x = rand() * W;
    const y = rand() * H;
    if (Math.hypot(x - W / 2, y - H * 0.47) < Math.min(W, H) * 0.3) continue;
    const w = 3 + rand() * 9;
    const h = 2 + rand() * 4;
    const warm = rand() < 0.18;
    g.fillStyle = warm ? `rgba(255,214,160,${0.05 + rand() * 0.12})` : `rgba(150,225,255,${0.05 + rand() * 0.16})`;
    g.fillRect(x, y, w, h);
  }

  g.filter = "none";
  g.strokeStyle = "rgba(90,200,255,.045)";
  g.lineWidth = 1;
  for (let x = 0; x < W; x += 32) {
    g.beginPath();
    g.moveTo(x + 0.5, 0);
    g.lineTo(x + 0.5, H);
    g.stroke();
  }
  for (let y = 0; y < H; y += 32) {
    g.beginPath();
    g.moveTo(0, y + 0.5);
    g.lineTo(W, y + 0.5);
    g.stroke();
  }

  const vig = g.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.35, W / 2, H / 2, Math.max(W, H) * 0.8);
  vig.addColorStop(0, "rgba(2,6,14,0)");
  vig.addColorStop(1, "rgba(2,6,14,.85)");
  g.fillStyle = vig;
  g.fillRect(0, 0, W, H);

  return cv;
}
