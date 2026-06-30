import { useCallback, useEffect, useRef } from "react";

import type { SubgraphSlice } from "../types";

type Phase = "inject" | "cascade" | "collapse" | "investigate" | "propose" | "resolution";

const COLOR_OK: [number, number, number] = [19, 153, 213];
const COLOR_DEGRADED: [number, number, number] = [230, 120, 0];
const COLOR_FAILED: [number, number, number] = [255, 62, 85];
const COLOR_OFFLINE: [number, number, number] = [120, 120, 140];
const COLOR_ISOLATED: [number, number, number] = [180, 100, 255];
const COLOR_MISCONFIG: [number, number, number] = [255, 220, 50];
const COLOR_DIM: [number, number, number] = [60, 60, 70];
const COLOR_HIGHLIGHT: [number, number, number] = [100, 220, 255];
const COLOR_BG = "#0e1117";

const STATUS_COLORS: Record<string, [number, number, number]> = {
  ok: COLOR_OK,
  degraded: COLOR_DEGRADED,
  failed: COLOR_FAILED,
  offline: COLOR_OFFLINE,
  isolated: COLOR_ISOLATED,
  misconfigured: COLOR_MISCONFIG,
};

function statusColor(status: string): [number, number, number] {
  return STATUS_COLORS[status] ?? COLOR_FAILED;
}

function rgb(c: [number, number, number], a = 1): string {
  return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
}

interface ForceNode {
  id: string;
  nodeType: string;
  name: string;
  status: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  isTarget: boolean;
}

interface ForceEdge {
  src: string;
  dst: string;
  type: string;
}

function buildForceNodes(
  nodes: SubgraphSlice["nodes"],
  target: string,
  w: number,
  h: number,
): ForceNode[] {
  const cx = w / 2;
  const cy = h / 2;
  return nodes.map((n, i) => {
    if (n.id === target) {
      return {
        id: n.id, nodeType: n.node_type, name: n.name, status: n.status,
        x: cx, y: cy, vx: 0, vy: 0, radius: 20, isTarget: true,
      };
    }
    const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2;
    const spread = Math.min(w, h) * 0.3;
    return {
      id: n.id, nodeType: n.node_type, name: n.name, status: n.status,
      x: cx + Math.cos(angle) * spread + (Math.random() - 0.5) * 20,
      y: cy + Math.sin(angle) * spread + (Math.random() - 0.5) * 20,
      vx: 0, vy: 0, radius: 12, isTarget: false,
    };
  });
}

function simulateForces(nodes: ForceNode[], edges: ForceEdge[], w: number, h: number): void {
  const cx = w / 2;
  const cy = h / 2;
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = 800 / (dist * dist);
      dx = (dx / dist) * force;
      dy = (dy / dist) * force;
      a.vx -= dx;
      a.vy -= dy;
      b.vx += dx;
      b.vy += dy;
    }
  }

  for (const e of edges) {
    const a = nodeMap.get(e.src);
    const b = nodeMap.get(e.dst);
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const target = 100;
    const force = (dist - target) * 0.02;
    const fx = (dx / dist) * force;
    const fy = (dy / dist) * force;
    a.vx += fx;
    a.vy += fy;
    b.vx -= fx;
    b.vy -= fy;
  }

  for (const n of nodes) {
    const dx = cx - n.x;
    const dy = cy - n.y;
    n.vx += dx * 0.001;
    n.vy += dy * 0.001;
  }

  for (const n of nodes) {
    if (n.isTarget) {
      n.x = cx;
      n.y = cy;
      n.vx = 0;
      n.vy = 0;
      continue;
    }
    n.vx *= 0.85;
    n.vy *= 0.85;
    n.x += n.vx;
    n.y += n.vy;
    n.x = Math.max(n.radius + 4, Math.min(w - n.radius - 4, n.x));
    n.y = Math.max(n.radius + 4, Math.min(h - n.radius - 4, n.y));
  }
}

function drawGraph(
  ctx: CanvasRenderingContext2D,
  nodes: ForceNode[],
  edges: ForceEdge[],
  phase: Phase,
  revealedSet: Set<string>,
  highlightNode: string | null,
  time: number,
  pan: { x: number; y: number },
): void {
  const dpr = window.devicePixelRatio || 1;
  const w = ctx.canvas.width / dpr;
  const h = ctx.canvas.height / dpr;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = COLOR_BG;
  ctx.fillRect(0, 0, w, h);
  ctx.save();
  ctx.translate(pan.x, pan.y);

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  for (const e of edges) {
    const a = nodeMap.get(e.src);
    const b = nodeMap.get(e.dst);
    if (!a || !b) continue;

    const srcRevealed = revealedSet.has(a.id);
    const dstRevealed = revealedSet.has(b.id);
    if (phase === "cascade" && !srcRevealed && !dstRevealed) continue;

    const bothRevealed = srcRevealed && dstRevealed;
    ctx.strokeStyle = bothRevealed ? "rgba(100,100,120,0.6)" : "rgba(60,60,70,0.3)";
    ctx.lineWidth = bothRevealed ? 1.5 : 1;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();

    if (bothRevealed) {
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist > 30) {
        const angle = Math.atan2(dy, dx);
        const ax = b.x - (dx / dist) * (b.radius + 4);
        const ay = b.y - (dy / dist) * (b.radius + 4);
        ctx.fillStyle = "rgba(100,100,120,0.6)";
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(ax - 6 * Math.cos(angle - 0.4), ay - 6 * Math.sin(angle - 0.4));
        ctx.lineTo(ax - 6 * Math.cos(angle + 0.4), ay - 6 * Math.sin(angle + 0.4));
        ctx.fill();

        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        ctx.font = "9px sans-serif";
        ctx.fillStyle = "rgba(120,120,140,0.7)";
        ctx.textAlign = "center";
        ctx.fillText(e.type.replace("carries_", "").replace("_", " "), mx, my - 4);
      }
    }
  }

  const pulse = Math.sin(time * 4) * 0.5 + 0.5;

  for (const n of nodes) {
    const revealed = revealedSet.has(n.id);
    const isHighlight = n.id === highlightNode;

    let color: [number, number, number];
    let alpha = 1;

    if (phase === "inject") {
      if (n.isTarget) {
        color = COLOR_FAILED;
        alpha = 0.7 + pulse * 0.3;
      } else {
        color = COLOR_DIM;
        alpha = 0.4;
      }
    } else if (phase === "cascade") {
      if (!revealed) {
        color = COLOR_DIM;
        alpha = 0.3;
      } else {
        color = statusColor(n.status);
      }
    } else if (phase === "collapse") {
      color = statusColor(n.status);
      alpha = n.isTarget ? 1 : 0.8;
    } else if (phase === "resolution") {
      color = COLOR_OK;
      alpha = 0.6 + pulse * 0.4;
    } else {
      color = statusColor(n.status);
    }

    ctx.beginPath();
    ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
    ctx.fillStyle = rgb(color, alpha);
    ctx.fill();

    if (n.isTarget && (phase === "inject" || phase === "cascade" || phase === "collapse")) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius + 4 + pulse * 3, 0, Math.PI * 2);
      ctx.strokeStyle = rgb(COLOR_FAILED, 0.4 + pulse * 0.4);
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    if (isHighlight) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius + 6, 0, Math.PI * 2);
      ctx.strokeStyle = rgb(COLOR_HIGHLIGHT, 0.6 + pulse * 0.4);
      ctx.lineWidth = 3;
      ctx.stroke();
    }

    ctx.font = n.isTarget ? "bold 10px sans-serif" : "9px sans-serif";
    ctx.fillStyle = revealed || phase !== "cascade" ? "rgba(200,200,210,0.9)" : "rgba(100,100,110,0.4)";
    ctx.textAlign = "center";
    const label = n.name.length > 18 ? n.name.slice(0, 16) + "…" : n.name;
    ctx.fillText(label, n.x, n.y + n.radius + 12);

    ctx.font = "8px sans-serif";
    ctx.fillStyle = "rgba(140,140,160,0.6)";
    ctx.fillText(n.nodeType, n.x, n.y + n.radius + 22);
  }

  ctx.restore();
}

interface SubgraphCanvasProps {
  subgraph: SubgraphSlice | null;
  phase: Phase;
  revealedSet: Set<string>;
  highlightNode: string | null;
  phaseLabel: string;
  phaseDetail: string;
}

export default function SubgraphCanvas({
  subgraph, phase, revealedSet, highlightNode, phaseLabel, phaseDetail,
}: SubgraphCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const forceNodesRef = useRef<ForceNode[]>([]);
  const forceEdgesRef = useRef<ForceEdge[]>([]);
  const animFrameRef = useRef(0);
  const timeRef = useRef(0);
  const panRef = useRef({ x: 0, y: 0 });
  const dragRef = useRef<{ x: number; y: number } | null>(null);

  const resizeCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;
    const dpr = window.devicePixelRatio || 1;
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    if (w === 0 || h === 0) return;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { w, h };
  }, []);

  useEffect(() => {
    if (!subgraph || !canvasRef.current) return;
    const dims = resizeCanvas();
    const w = dims?.w ?? 800;
    const h = dims?.h ?? 600;

    forceNodesRef.current = buildForceNodes(subgraph.nodes, subgraph.target, w, h);
    forceEdgesRef.current = subgraph.edges.map((e) => ({ src: e.src, dst: e.dst, type: e.type }));
    panRef.current = { x: 0, y: 0 };
  }, [subgraph, resizeCanvas]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !canvas.parentElement) return;
    const observer = new ResizeObserver(() => {
      const dims = resizeCanvas();
      if (dims && forceNodesRef.current.length > 0) {
        const { w, h } = dims;
        for (const n of forceNodesRef.current) {
          n.x = Math.max(n.radius + 4, Math.min(w - n.radius - 4, n.x));
          n.y = Math.max(n.radius + 4, Math.min(h - n.radius - 4, n.y));
        }
      }
    });
    observer.observe(canvas.parentElement);
    return () => observer.disconnect();
  }, [subgraph, resizeCanvas]);

  useEffect(() => {
    if (!canvasRef.current || !subgraph) return;
    const ctx = canvasRef.current.getContext("2d");
    if (!ctx) return;

    let running = true;
    const loop = () => {
      if (!running) return;
      timeRef.current += 0.016;
      const parent = canvasRef.current!.parentElement;
      const w = parent?.clientWidth ?? 800;
      const h = parent?.clientHeight ?? 600;
      simulateForces(forceNodesRef.current, forceEdgesRef.current, w, h);
      drawGraph(
        ctx, forceNodesRef.current, forceEdgesRef.current,
        phase, revealedSet, highlightNode, timeRef.current, panRef.current,
      );
      animFrameRef.current = requestAnimationFrame(loop);
    };
    loop();

    return () => {
      running = false;
      cancelAnimationFrame(animFrameRef.current);
    };
  }, [subgraph, phase, revealedSet, highlightNode]);

  if (!subgraph) {
    return <div className="sg-empty">Select an incident to visualize</div>;
  }

  return (
    <>
      <canvas
        ref={canvasRef}
        className="sg-canvas"
        onMouseDown={(e) => { dragRef.current = { x: e.clientX, y: e.clientY }; }}
        onMouseMove={(e) => {
          if (!dragRef.current) return;
          panRef.current = {
            x: panRef.current.x + (e.clientX - dragRef.current.x),
            y: panRef.current.y + (e.clientY - dragRef.current.y),
          };
          dragRef.current = { x: e.clientX, y: e.clientY };
        }}
        onMouseUp={() => { dragRef.current = null; }}
        onMouseLeave={() => { dragRef.current = null; }}
      />
      <div className="sg-overlay">
        <div className="sg-overlay-title">{phaseLabel}</div>
        <div className="sg-overlay-body">{phaseDetail}</div>
      </div>
      <div className="sg-legend">
        {Object.entries(STATUS_COLORS).map(([label, color]) => (
          <div key={label} className="sg-legend-item">
            <span className="sg-legend-dot" style={{ background: rgb(color) }} />
            <span className="sg-legend-label">{label}</span>
          </div>
        ))}
      </div>
    </>
  );
}
