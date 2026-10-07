import React, { useEffect, useRef } from "react";
import { SimulatedBadge } from "../components/SimulatedBadge";
import type { SimulatedAgentNode } from "../fixtures/dashboardFixture";
import { createMulberry32 } from "./seededRandom";

interface NeuralSceneProps {
  nodes: SimulatedAgentNode[];
  isFrozen?: boolean;
}

export const NeuralScene: React.FC<NeuralSceneProps> = ({ nodes, isFrozen = false }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId = 0;
    const rng = createMulberry32(0x4f88bc12);

    // Pre-calculate fixed star positions using deterministic random generator
    const stars: { x: number; y: number; r: number; alpha: number }[] = [];
    for (let i = 0; i < 120; i++) {
      stars.push({
        x: rng(),
        y: rng(),
        r: rng() * 1.5 + 0.5,
        alpha: rng() * 0.5 + 0.2
      });
    }

    const render = (time: number) => {
      const W = canvas.width;
      const H = canvas.height;

      ctx.clearRect(0, 0, W, H);

      // Deep space radial background
      const grad = ctx.createRadialGradient(W / 2, H * 0.45, 10, W / 2, H * 0.45, W * 0.6);
      grad.addColorStop(0, "#081a2e");
      grad.addColorStop(0.5, "#040e1a");
      grad.addColorStop(1, "#02070f");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, W, H);

      // Deterministic starry background
      stars.forEach((star) => {
        ctx.beginPath();
        ctx.arc(star.x * W, star.y * H, star.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(142, 174, 194, ${star.alpha})`;
        ctx.fill();
      });

      // Central Hermes Core Geometry (Concentric rings & pulsing pedestal)
      const cx = W / 2;
      const cy = H * 0.45;
      const t = isFrozen ? 0 : time * 0.001;

      // Outer dashed orbital ring
      ctx.beginPath();
      ctx.ellipse(cx, cy, 180, 50, 0, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(56, 232, 255, 0.25)";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([8, 12]);
      ctx.lineDashOffset = -t * 20;
      ctx.stroke();
      ctx.setLineDash([]);

      // Middle steady ring
      ctx.beginPath();
      ctx.ellipse(cx, cy, 140, 38, 0, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(56, 232, 255, 0.45)";
      ctx.lineWidth = 1.2;
      ctx.stroke();

      // Core glow halo
      const halo = ctx.createRadialGradient(cx, cy, 5, cx, cy, 70);
      halo.addColorStop(0, "rgba(56, 232, 255, 0.6)");
      halo.addColorStop(0.4, "rgba(56, 232, 255, 0.2)");
      halo.addColorStop(1, "rgba(56, 232, 255, 0)");
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(cx, cy, 70, 0, Math.PI * 2);
      ctx.fill();

      // Core central sphere
      ctx.beginPath();
      ctx.arc(cx, cy, 26, 0, Math.PI * 2);
      ctx.fillStyle = "#38e8ff";
      ctx.shadowColor = "#38e8ff";
      ctx.shadowBlur = 18;
      ctx.fill();
      ctx.shadowBlur = 0;

      // Draw multi-strand connection fibers to flank nodes
      const leftNodes = nodes.slice(0, 3);
      const rightNodes = nodes.slice(3, 6);

      const drawFiber = (fromX: number, fromY: number, toX: number, toY: number, dashed: boolean) => {
        ctx.beginPath();
        ctx.moveTo(fromX, fromY);
        const midX = (fromX + toX) / 2;
        ctx.bezierCurveTo(midX, fromY, midX, toY, toX, toY);
        ctx.strokeStyle = dashed ? "rgba(107, 127, 166, 0.4)" : "rgba(79, 214, 255, 0.5)";
        ctx.lineWidth = 1.4;
        if (dashed) {
          ctx.setLineDash([4, 6]);
        } else {
          ctx.setLineDash([]);
        }
        ctx.stroke();
        ctx.setLineDash([]);
      };

      leftNodes.forEach((_, idx) => {
        const nx = W * 0.18;
        const ny = H * (0.2 + idx * 0.28);
        drawFiber(cx, cy, nx, ny, true);
      });

      rightNodes.forEach((_, idx) => {
        const nx = W * 0.82;
        const ny = H * (0.2 + idx * 0.28);
        drawFiber(cx, cy, nx, ny, true);
      });

      if (!isFrozen) {
        animId = requestAnimationFrame(render);
      }
    };

    const handleResize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
      render(0);
    };

    handleResize();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      if (animId) cancelAnimationFrame(animId);
    };
  }, [nodes, isFrozen]);

  return (
    <div className="glass hud-frame" style={{ position: "relative", minHeight: "520px", width: "100%", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: "14px", left: "16px", zIndex: 10, display: "flex", alignItems: "center", gap: "10px" }}>
        <h2 className="disp" style={{ fontSize: "16px", color: "var(--sun2)" }}>
          Neural Command Scene
        </h2>
        <SimulatedBadge label="CANVAS 2D SCAFFOLD" />
      </div>

      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: "100%", minHeight: "520px", display: "block" }}
      />

      <div
        style={{
          position: "absolute",
          bottom: "12px",
          left: "16px",
          right: "16px",
          zIndex: 10,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: "12px",
          color: "var(--mu)"
        }}
      >
        <span className="tech">HERMES CORE: OBSERVED-ONLY (OFFLINE)</span>
        <span className="tech">ENGINE: DETERMINISTIC CANVAS 2D (PRNG MULBERRY32)</span>
      </div>
    </div>
  );
};