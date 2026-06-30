import { useEffect, useMemo, useRef, useState } from "react";

import type { Incident, NetGraph, NetNode } from "../types";

// Radial layout: PLANT core at centre, sections as wedges, devices on rings by
// Purdue level (gateway inner → field devices outer).
const LEVEL_R: Record<number, number> = { 4: 0, 3: 120, 2: 205, 1: 300, 0: 420 };
const NODE_R: Record<number, number> = { 4: 16, 3: 9, 2: 8, 1: 7, 0: 5 };

const TYPE_COLOR: Record<string, string> = {
  sensor: "#4FA3D1", gas: "#36C5F0", valve: "#6FAE8F", mov: "#6FAE8F", pump: "#C9A24B",
  plc: "#B08CC9", dcs: "#B08CC9", sis: "#E0857A", rtu: "#8AA0B8",
  switch: "#7F8C9A", gateway: "#9AA6B2", workstation: "#C0C8D0", plant: "#E8F0FB",
};
const LEGEND = ["sensor", "valve", "pump", "dcs", "sis", "switch", "gateway", "workstation"];

// The 6-phase incident investigation — the whole point of this tab.
const PHASES = [
  { key: "inject", icon: "⚡", label: "Inject" },
  { key: "cascade", icon: "🔗", label: "Cascade" },
  { key: "collapse", icon: "💀", label: "Collapse" },
  { key: "investigate", icon: "🔍", label: "Investigate" },
  { key: "propose", icon: "💡", label: "Propose" },
  { key: "resolution", icon: "✅", label: "Resolve" },
] as const;

// Vulcan (local AI) runs the SAME deterministic 5-step diagnosis every time — the
// provability story: not a hallucinating LLM, the same provable steps every run.
const VULCAN_STEPS = [
  "Read plant state",
  "Enumerate open incidents",
  "Trace cascade → root cause",
  "Match failure mode → remediation",
  "Prove & propose action",
];

const REMEDIATION: Record<string, string> = {
  element_offline: "Promote digital twin — serve last-known state from a replica",
  switch_down: "Reroute the section through its redundant gateway",
  loss_of_utility: "Fail over to the backup utility feed",
  pump_vibration: "Isolate pump, start the standby",
  unit_trip: "Reset interlock and restart the unit",
  gas_release: "Purge, confirm gas cleared, then restart",
};
const SAFE = new Set(["element_offline", "switch_down", "loss_of_utility", "pump_vibration"]);

function nodeColor(n: NetNode): string {
  if (n.in_trip || n.state === "down") return "var(--crit)";
  if (n.in_alarm) return "var(--warn)";
  return TYPE_COLOR[n.type] ?? "#8AA0B8";
}

interface Props {
  graph: NetGraph | null;
  incidents?: Incident[];
  onHeal?: (seq: number) => void;
}

export function InvestigateView({ graph, incidents = [], onHeal }: Props) {
  const active = incidents.filter((i) => !i.resolved).at(-1);
  const [phase, setPhase] = useState(0);
  const [step, setStep] = useState(0);
  const [vStep, setVStep] = useState(0); // Vulcan 5-step diagnosis progress
  const [playing, setPlaying] = useState(false);
  const seqRef = useRef<number | undefined>(undefined);
  const healedRef = useRef<number | undefined>(undefined);

  // A new incident starts a fresh investigation, auto-playing from Inject.
  useEffect(() => {
    if (!active) {
      seqRef.current = undefined;
      setPhase(0);
      setStep(0);
      setVStep(0);
      setPlaying(false);
      return;
    }
    if (seqRef.current !== active.seq) {
      seqRef.current = active.seq;
      setPhase(0);
      setStep(0);
      setVStep(0);
      setPlaying(true);
    }
  }, [active]);

  // Auto-advance: cascade walks node-by-node, the Investigate phase runs Vulcan's 5
  // deterministic steps, then it pauses at Propose for the apply/approve decision.
  useEffect(() => {
    if (!active || !playing) return;
    const dwell = phase === 1 ? 320 : phase === 3 ? 480 : 1100;
    const t = setTimeout(() => {
      if (phase === 1 && step < active.affected.length) {
        setStep((s) => s + 1);
      } else if (phase === 3 && vStep < VULCAN_STEPS.length) {
        setVStep((v) => v + 1);
      } else if (phase < 4) {
        setPhase((p) => p + 1);
        setStep(0);
      } else {
        setPlaying(false); // stop at Propose — wait for Apply/Approve
      }
    }, dwell);
    return () => clearTimeout(t);
  }, [active, playing, phase, step, vStep]);

  const phaseKey = PHASES[phase].key;
  // Which affected items are "revealed" red: a growing prefix during cascade, all after.
  const revealedSet = useMemo(() => {
    if (!active) return new Set<string>();
    const n = phaseKey === "cascade" ? step : active.affected.length;
    return new Set(active.affected.slice(0, n));
  }, [active, phaseKey, step]);

  const rootId = active?.affected[0]; // BFS origin = the root cause
  const isStruck = (n: NetNode) => revealedSet.has(n.id) || (n.unit ? revealedSet.has(n.unit) : false);
  const isRoot = (n: NetNode) =>
    !!active && (n.id === rootId || (n.unit && n.unit === rootId)) &&
    (phaseKey === "investigate" || phaseKey === "propose" || phaseKey === "resolution");

  const layout = useMemo(() => {
    if (!graph) return null;
    const cx = 500, cy = 500;
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
      const stepA = arr.length > 1 ? span / arr.length : 0;
      arr.forEach((n, i) => {
        const a = base + (i - (arr.length - 1) / 2) * stepA;
        pos.set(n.id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
      });
    }
    return { pos };
  }, [graph]);

  if (!graph || !layout) return <div className="loading">Loading network…</div>;
  const { pos } = layout;

  const safe = active ? SAFE.has(active.kind) : false;
  const caption = !active
    ? "No active incident — inject a fault on the Overview tab to investigate."
    : phaseKey === "inject"
      ? `⚡ Fault injected: ${active.kind} at ${active.target}`
      : phaseKey === "cascade"
        ? `🔗 Failure propagating… ${Math.min(step, active.affected.length)}/${active.affected.length} affected`
        : phaseKey === "collapse"
          ? `💀 Blast radius: ${active.affected.length} elements down`
          : phaseKey === "investigate"
            ? `🔍 Vulcan diagnosing… ROOT CAUSE: ${rootId} (${active.kind})`
            : phaseKey === "propose"
              ? `💡 Vulcan proposes: ${REMEDIATION[active.kind] ?? "manual intervention"} — ${safe ? "safe, auto-heal" : "SIS/gas, needs approval"}`
              : `✅ Resolved by Vulcan — ${active.affected.length} elements restored`;

  return (
    <div className="investigate" data-testid="investigate">
      <div className="inv-head">
        <span className="inv-title">OT NETWORK — incident investigation</span>
        <div className="inv-legend">
          {LEGEND.map((t) => (
            <span key={t} className="leg"><i style={{ background: TYPE_COLOR[t] }} /> {t}</span>
          ))}
          <span className="leg"><i style={{ background: "var(--crit)" }} /> tripped/down</span>
        </div>
      </div>

      {active && (
        <div className="inv-phases" data-testid="inv-phases">
          {PHASES.map((p, i) => (
            <span key={p.key} className={`inv-phase${i === phase ? " active" : ""}${i < phase ? " done" : ""}`}>
              <b>{p.icon}</b> {p.label}
            </span>
          ))}
        </div>
      )}

      {active && phase >= 3 && (
        <div className="vulcan" data-testid="vulcan">
          <div className="vulcan-head">
            🔒 VULCAN · local AI
            <span className="vulcan-tag">deterministic — same 5 steps, every run</span>
          </div>
          <ol className="vulcan-steps">
            {VULCAN_STEPS.map((s, i) => (
              <li
                key={i}
                className={i < vStep ? "done" : phaseKey === "investigate" && i === vStep ? "active" : ""}
              >
                <b>{i < vStep ? "✓" : phaseKey === "investigate" && i === vStep ? "▸" : "·"}</b> {s}
                {i === 2 && i < vStep && <em> → {rootId}</em>}
              </li>
            ))}
          </ol>
        </div>
      )}

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
            const struck = isStruck(n);
            const root = isRoot(n);
            const dim = !!active && phaseKey !== "inject" && phaseKey !== "resolution" && !struck && !root;
            const fill = struck && active ? "var(--crit)" : nodeColor(n);
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.18 : 1}>
                {root && <circle r={r + 7} className="root-ring" data-testid="root-ring" />}
                <circle
                  r={r}
                  fill={fill}
                  className={`node${struck ? " cascading" : ""}`}
                  data-testid={`net-${n.id}`}
                >
                  <title>{n.id} · {n.type} · {n.state}</title>
                </circle>
                {(n.level >= 2 || root) && <text className="net-label" y={-r - 3}>{n.id}</text>}
              </g>
            );
          })}
        </g>
      </svg>

      <div className="inv-foot" data-testid="inv-caption">
        <span className="inv-caption">{caption}</span>
        {active && (
          <span className="inv-transport">
            <button onClick={() => setPlaying((v) => !v)} data-testid="inv-play">
              {playing ? "⏸" : "▶"}
            </button>
            <button
              onClick={() => {
                if (phase === 1 && step < active.affected.length) setStep((s) => s + 1);
                else setPhase((p) => Math.min(p + 1, PHASES.length - 1));
              }}
              data-testid="inv-step"
            >
              ⏭ Step
            </button>
            {phaseKey === "propose" && (
              <button
                className={safe ? "inv-apply safe" : "inv-apply danger"}
                data-testid="inv-apply"
                onClick={() => {
                  if (active && healedRef.current !== active.seq) {
                    healedRef.current = active.seq;
                    onHeal?.(active.seq);
                  }
                  setPhase(5);
                }}
              >
                {safe ? "Auto-heal" : "Approve & heal"}
              </button>
            )}
          </span>
        )}
      </div>
    </div>
  );
}
