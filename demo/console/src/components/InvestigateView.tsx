import { useEffect, useMemo, useRef, useState } from "react";

import type { Incident, NetGraph, NetNode } from "../types";

// Radial layout: PLANT core at centre, sections as wedges, devices on rings by
// Purdue level (gateway inner → field devices outer).
const LEVEL_R: Record<number, number> = { 4: 0, 3: 120, 2: 205, 1: 300, 0: 420 };
const NODE_R: Record<number, number> = { 4: 16, 3: 9, 2: 8, 1: 7, 0: 5 };

const TYPE_COLOR: Record<string, string> = {
  sensor: "#4FA3D1",
  gas: "#36C5F0",
  valve: "#6FAE8F",
  mov: "#6FAE8F",
  pump: "#C9A24B",
  plc: "#B08CC9",
  dcs: "#B08CC9",
  sis: "#E0857A",
  rtu: "#8AA0B8",
  switch: "#7F8C9A",
  gateway: "#9AA6B2",
  workstation: "#C0C8D0",
  plant: "#E8F0FB",
};

const LEGEND = ["sensor", "valve", "pump", "dcs", "sis", "switch", "gateway", "workstation"];

function nodeColor(n: NetNode): string {
  if (n.in_trip || n.state === "down") return "var(--crit)";
  if (n.in_alarm) return "var(--warn)";
  return TYPE_COLOR[n.type] ?? "#8AA0B8";
}

function nodeOpacity(n: NetNode): number {
  return n.state === "offline" || n.state === "discovered" ? 0.35 : 1;
}

export function InvestigateView({
  graph,
  incidents = [],
}: {
  graph: NetGraph | null;
  incidents?: Incident[];
}) {
  // Node-walk: reveal the active incident's cascade (BFS-ordered `affected`) one step
  // at a time so the trip visibly propagates outward, then clears when it heals.
  const active = incidents.filter((i) => !i.resolved).at(-1);
  const [reveal, setReveal] = useState(0);
  const seqRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!active) {
      setReveal(0);
      return;
    }
    if (seqRef.current !== active.seq) {
      seqRef.current = active.seq;
      setReveal(0);
    }
    const id = setInterval(
      () => setReveal((r) => Math.min(r + 1, active.affected.length)),
      280,
    );
    return () => clearInterval(id);
  }, [active]);

  const pulsing = useMemo(() => {
    const ids = new Set<string>();
    if (!active || !graph) return ids;
    const revealed = new Set(active.affected.slice(0, reveal));
    for (const n of graph.nodes) {
      if (revealed.has(n.id) || (n.unit && revealed.has(n.unit))) ids.add(n.id);
    }
    return ids;
  }, [active, reveal, graph]);

  const layout = useMemo(() => {
    if (!graph) return null;
    const cx = 500;
    const cy = 500;
    const sections = [...new Set(graph.nodes.filter((n) => n.section).map((n) => n.section))];
    const secAngle = new Map(
      sections.map((s, i) => [s, (i / sections.length) * 2 * Math.PI - Math.PI / 2]),
    );
    const groups = new Map<string, NetNode[]>();
    for (const n of graph.nodes) {
      if (n.type === "plant") continue;
      const k = `${n.section}|${n.level}`;
      const arr = groups.get(k) ?? [];
      arr.push(n);
      groups.set(k, arr);
    }
    const pos = new Map<string, { x: number; y: number }>([["PLANT", { x: cx, y: cy }]]);
    const span = ((2 * Math.PI) / sections.length) * 0.82;
    for (const [k, arr] of groups) {
      const [sec, lvl] = k.split("|");
      const base = secAngle.get(sec) ?? 0;
      const r = LEVEL_R[Number(lvl)];
      const step = arr.length > 1 ? span / arr.length : 0;
      arr.forEach((n, i) => {
        const a = base + (i - (arr.length - 1) / 2) * step;
        pos.set(n.id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
      });
    }
    return { pos, sections, secAngle, cx, cy };
  }, [graph]);

  if (!graph || !layout) return <div className="loading">Loading network…</div>;
  const { pos } = layout;

  return (
    <div className="investigate" data-testid="investigate">
      <div className="inv-head">
        <span className="inv-title">OT NETWORK — device topology</span>
        <span className="inv-sub">
          {graph.nodes.length - 1} devices · Purdue L0→L3 → plant core
        </span>
        <div className="inv-legend">
          {LEGEND.map((t) => (
            <span key={t} className="leg">
              <i style={{ background: TYPE_COLOR[t] }} /> {t}
            </span>
          ))}
          <span className="leg">
            <i style={{ background: "var(--crit)" }} /> tripped/down
          </span>
        </div>
      </div>
      <svg viewBox="0 0 1000 1000" className="netsvg" preserveAspectRatio="xMidYMid meet">
        <g className="edges">
          {graph.edges.map((e, i) => {
            const a = pos.get(e.src);
            const b = pos.get(e.dst);
            if (!a || !b) return null;
            return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
          })}
        </g>
        <g className="nodes">
          {graph.nodes.map((n) => {
            const p = pos.get(n.id);
            if (!p) return null;
            const r = NODE_R[n.level] ?? 6;
            const alert = n.in_trip || n.state === "down" || n.in_alarm;
            const walking = pulsing.has(n.id);
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={nodeOpacity(n)}>
                <circle
                  r={r}
                  fill={nodeColor(n)}
                  className={`node${alert ? " alert" : ""}${walking ? " cascading" : ""}`}
                  data-testid={`net-${n.id}`}
                  data-state={n.state}
                >
                  <title>
                    {n.id} · {n.type}
                    {n.value !== null ? ` · ${n.value}` : ""} · {n.state}
                  </title>
                </circle>
                {n.level >= 2 && (
                  <text className="net-label" y={-r - 3}>
                    {n.id}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
