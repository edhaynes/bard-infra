import { useEffect, useMemo, useRef, useState } from "react";

import type { Incident, NetGraph, NetNode } from "../types";

const NODE_R: Record<number, number> = { 4: 16, 3: 9, 2: 8, 1: 7, 0: 5 };
const TYPE_COLOR: Record<string, string> = {
  sensor: "#4FA3D1", gas: "#36C5F0", valve: "#6FAE8F", mov: "#6FAE8F", pump: "#C9A24B",
  plc: "#B08CC9", dcs: "#B08CC9", sis: "#E0857A", rtu: "#8AA0B8",
  switch: "#7F8C9A", gateway: "#9AA6B2", workstation: "#C0C8D0", plant: "#E8F0FB",
};
const LEGEND = ["sensor", "valve", "pump", "dcs", "sis", "switch", "gateway", "workstation"];

// Purdue levels, top (plant) to bottom (field) — the conventional OT pyramid.
const PURDUE_TIERS = [
  { level: 4, y: 60, label: "L4 · Plant" },
  { level: 3, y: 215, label: "L3 · Gateways" },
  { level: 2, y: 380, label: "L2 · Supervisory" },
  { level: 1, y: 575, label: "L1 · Control" },
  { level: 0, y: 850, label: "L0 · Field devices" },
];
const PYRAMID_W = 1500;
const PYRAMID_H = 940;

const PHASES = [
  { key: "inject", icon: "⚡", label: "Inject" },
  { key: "cascade", icon: "🔗", label: "Cascade" },
  { key: "collapse", icon: "💀", label: "Collapse" },
  { key: "investigate", icon: "🔍", label: "Investigate" },
  { key: "propose", icon: "💡", label: "Propose" },
  { key: "resolution", icon: "✅", label: "Resolve" },
] as const;

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
const MODELS = [
  { id: "vulcan", label: "Vulcan — local · deterministic" },
  { id: "claude", label: "Claude — cloud" },
  { id: "gpt4", label: "GPT-4 — cloud" },
];

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
  const [vStep, setVStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [model, setModel] = useState("vulcan");
  const [shape, setShape] = useState<"pyramid" | "radial">("pyramid");
  const [rejected, setRejected] = useState<number | undefined>(undefined);
  const seqRef = useRef<number | undefined>(undefined);
  const healedRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!active) {
      seqRef.current = undefined;
      setPhase(0); setStep(0); setVStep(0); setPlaying(false);
      return;
    }
    if (seqRef.current !== active.seq) {
      seqRef.current = active.seq;
      setPhase(0); setStep(0); setVStep(0); setPlaying(true);
    }
  }, [active]);

  useEffect(() => {
    if (!active || !playing) return;
    const dwell = phase === 1 ? 320 : phase === 3 ? 480 : 1100;
    const t = setTimeout(() => {
      if (phase === 1 && step < active.affected.length) setStep((s) => s + 1);
      else if (phase === 3 && vStep < VULCAN_STEPS.length) setVStep((v) => v + 1);
      else if (phase < 4) { setPhase((p) => p + 1); setStep(0); }
      else setPlaying(false); // pause at Propose for the human decision
    }, dwell);
    return () => clearTimeout(t);
  }, [active, playing, phase, step, vStep]);

  const phaseKey = PHASES[phase].key;
  const rootId = active?.affected[0];
  const revealedSet = useMemo(() => {
    if (!active) return new Set<string>();
    const n = phaseKey === "cascade" ? step : active.affected.length;
    return new Set(active.affected.slice(0, n));
  }, [active, phaseKey, step]);
  const isStruck = (n: NetNode) => revealedSet.has(n.id) || (n.unit ? revealedSet.has(n.unit) : false);
  const isRoot = (n: NetNode) =>
    !!active && (n.id === rootId || (n.unit && n.unit === rootId)) &&
    (phaseKey === "investigate" || phaseKey === "propose" || phaseKey === "resolution");

  const layout = useMemo(() => {
    if (!graph) return null;
    const pos = new Map<string, { x: number; y: number }>();
    if (shape === "pyramid") {
      const sections = [...new Set(graph.nodes.filter((n) => n.section).map((n) => n.section))];
      const secIdx = new Map(sections.map((s, i) => [s, i]));
      const byLevel = new Map<number, NetNode[]>();
      for (const n of graph.nodes) {
        const arr = byLevel.get(n.level) ?? [];
        arr.push(n);
        byLevel.set(n.level, arr);
      }
      for (const tier of PURDUE_TIERS) {
        const arr = (byLevel.get(tier.level) ?? []).slice().sort((a, b) =>
          (secIdx.get(a.section) ?? 0) - (secIdx.get(b.section) ?? 0) || a.id.localeCompare(b.id),
        );
        const m = 90;
        arr.forEach((n, i) => {
          const x = arr.length === 1 ? PYRAMID_W / 2 : m + (i + 0.5) * ((PYRAMID_W - 2 * m) / arr.length);
          pos.set(n.id, { x, y: tier.y });
        });
      }
      return { pos, vb: `0 0 ${PYRAMID_W} ${PYRAMID_H}` };
    }
    // radial
    const cx = 500, cy = 500;
    const R: Record<number, number> = { 4: 0, 3: 120, 2: 205, 1: 300, 0: 420 };
    const sections = [...new Set(graph.nodes.filter((n) => n.section).map((n) => n.section))];
    const secAngle = new Map(sections.map((s, i) => [s, (i / sections.length) * 2 * Math.PI - Math.PI / 2]));
    const groups = new Map<string, NetNode[]>();
    for (const n of graph.nodes) {
      if (n.type === "plant") continue;
      const k = `${n.section}|${n.level}`;
      const arr = groups.get(k) ?? [];
      arr.push(n);
      groups.set(k, arr);
    }
    pos.set("PLANT", { x: cx, y: cy });
    const span = ((2 * Math.PI) / sections.length) * 0.82;
    for (const [k, arr] of groups) {
      const [sec, lvl] = k.split("|");
      const base = secAngle.get(sec) ?? 0;
      const r = R[Number(lvl)];
      const stepA = arr.length > 1 ? span / arr.length : 0;
      arr.forEach((n, i) => {
        const a = base + (i - (arr.length - 1) / 2) * stepA;
        pos.set(n.id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
      });
    }
    return { pos, vb: "0 0 1000 1000" };
  }, [graph, shape]);

  if (!graph || !layout) return <div className="loading">Loading network…</div>;
  const { pos, vb } = layout;
  const safe = active ? SAFE.has(active.kind) : false;
  const isRejected = active && rejected === active.seq;
  const det = model === "vulcan";

  const caption = !active
    ? "No active incident — inject a fault on the Overview tab to investigate."
    : isRejected
      ? "✋ Operator rejected the remediation — incident remains open."
      : phaseKey === "inject" ? `⚡ Fault injected: ${active.kind} at ${active.target}`
      : phaseKey === "cascade" ? `🔗 Failure propagating… ${Math.min(step, active.affected.length)}/${active.affected.length} affected`
      : phaseKey === "collapse" ? `💀 Blast radius: ${active.affected.length} elements down`
      : phaseKey === "investigate" ? `🔍 ${det ? "Vulcan" : model} diagnosing… ROOT CAUSE: ${rootId} (${active.kind})`
      : phaseKey === "propose" ? `💡 ${det ? "Vulcan" : model} proposes: ${REMEDIATION[active.kind] ?? "manual"} — ${safe ? "safe" : "SIS/gas, needs approval"}`
      : `✅ Resolved — ${active.affected.length} elements restored`;

  return (
    <div className="investigate" data-testid="investigate">
      <div className="inv-head">
        <span className="inv-title">OT NETWORK — incident investigation</span>
        <label className="inv-model-pick">
          model
          <select value={model} onChange={(e) => setModel(e.target.value)} data-testid="inv-model">
            {MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
        <button className="inv-shape" data-testid="inv-shape" onClick={() => setShape((s) => (s === "pyramid" ? "radial" : "pyramid"))}>
          {shape === "pyramid" ? "◇ Radial" : "▲ Pyramid"}
        </button>
        <div className="inv-legend">
          {LEGEND.map((t) => <span key={t} className="leg"><i style={{ background: TYPE_COLOR[t] }} /> {t}</span>)}
          <span className="leg"><i style={{ background: "var(--crit)" }} /> tripped</span>
        </div>
      </div>

      {active && !isRejected && (
        <div className="inv-phases" data-testid="inv-phases">
          {PHASES.map((p, i) => (
            <span key={p.key} className={`inv-phase${i === phase ? " active" : ""}${i < phase ? " done" : ""}`}>
              <b>{p.icon}</b> {p.label}
            </span>
          ))}
        </div>
      )}

      {active && !isRejected && phase >= 3 && (
        <div className="vulcan" data-testid="vulcan">
          <div className="vulcan-head">
            🔒 {det ? "VULCAN · local AI" : `${model} · cloud LLM`}
            <span className="vulcan-tag">{det ? "deterministic — same 5 steps, every run" : "cloud — may vary run to run"}</span>
          </div>
          <ol className="vulcan-steps">
            {VULCAN_STEPS.map((s, i) => (
              <li key={i} className={i < vStep ? "done" : phaseKey === "investigate" && i === vStep ? "active" : ""}>
                <b>{i < vStep ? "✓" : phaseKey === "investigate" && i === vStep ? "▸" : "·"}</b> {s}
                {i === 2 && i < vStep && <em> → {rootId}</em>}
              </li>
            ))}
          </ol>
        </div>
      )}

      <svg viewBox={vb} className="netsvg" preserveAspectRatio="xMidYMid meet">
        {shape === "pyramid" &&
          PURDUE_TIERS.map((t) => (
            <text key={t.level} className="tier-label" x={12} y={t.y + 4}>{t.label}</text>
          ))}
        <g className="edges">
          {graph.edges.map((e, i) => {
            const a = pos.get(e.src), b = pos.get(e.dst);
            if (!a || !b) return null;
            return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
          })}
        </g>
        <g className="nodes">
          {graph.nodes.map((n) => {
            const p = pos.get(n.id);
            if (!p) return null;
            const r = NODE_R[n.level] ?? 6;
            const struck = isStruck(n), root = isRoot(n);
            const dim = !!active && !isRejected && phaseKey !== "inject" && phaseKey !== "resolution" && !struck && !root;
            const fill = struck && active && !isRejected ? "var(--crit)" : nodeColor(n);
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.18 : 1}>
                {root && <circle r={r + 7} className="root-ring" data-testid="root-ring" />}
                <circle r={r} fill={fill} className={`node${struck && !isRejected ? " cascading" : ""}`} data-testid={`net-${n.id}`}>
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
            <button onClick={() => setPlaying((v) => !v)} data-testid="inv-play">{playing ? "⏸" : "▶"}</button>
            <button
              data-testid="inv-step"
              onClick={() => {
                if (phase === 1 && step < active.affected.length) setStep((s) => s + 1);
                else setPhase((p) => Math.min(p + 1, PHASES.length - 1));
              }}
            >⏭ Step</button>
            {phaseKey === "propose" && !isRejected && (
              <>
                <button
                  className={safe ? "inv-approve safe" : "inv-approve"}
                  data-testid="inv-approve"
                  onClick={() => {
                    if (healedRef.current !== active.seq) { healedRef.current = active.seq; onHeal?.(active.seq); }
                    setPhase(5);
                  }}
                >✓ Approve{safe ? " (safe)" : ""}</button>
                <button className="inv-reject" data-testid="inv-reject" onClick={() => { setRejected(active.seq); setPlaying(false); }}>
                  ✕ Reject
                </button>
              </>
            )}
          </span>
        )}
      </div>
    </div>
  );
}
