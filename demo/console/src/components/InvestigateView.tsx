import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api";
import type { AgentStatus, Incident, SubgraphSlice } from "../types";
import { AgentPanel } from "./AgentPanel";
import SubgraphCanvas from "./SubgraphCanvas";

const PHASES = [
  { key: "inject", icon: "⚡", label: "Inject" },
  { key: "cascade", icon: "🔗", label: "Cascade" },
  { key: "collapse", icon: "💀", label: "Collapse" },
  { key: "investigate", icon: "🔍", label: "Investigate" },
  { key: "propose", icon: "💡", label: "Propose" },
  { key: "resolution", icon: "✅", label: "Resolve" },
] as const;

type Phase = (typeof PHASES)[number]["key"];

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

// cdn-sim's revealedNodes: target on inject, cascade_order walked on cascade, all otherwise.
function revealedNodes(sg: SubgraphSlice | null, phase: Phase, cascadeStep: number): Set<string> {
  const r = new Set<string>();
  if (!sg) return r;
  if (phase === "inject") {
    r.add(sg.target);
  } else if (phase === "cascade") {
    for (let i = 0; i <= cascadeStep && i < sg.cascade_order.length; i++) r.add(sg.cascade_order[i]);
  } else {
    for (const id of sg.cascade_order) r.add(id);
  }
  return r;
}

interface Props {
  incidents?: Incident[];
  agent: AgentStatus | null;
  onRefresh: () => void;
  onHeal?: (seq: number) => void;
}

export function InvestigateView({ incidents = [], agent, onRefresh, onHeal }: Props) {
  const active = incidents.filter((i) => !i.resolved).at(-1);
  const [subgraph, setSubgraph] = useState<SubgraphSlice | null>(null);
  const [phase, setPhase] = useState(0);
  const [step, setStep] = useState(0);
  const [vStep, setVStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rejected, setRejected] = useState<number | undefined>(undefined);
  const seqRef = useRef<number | undefined>(undefined);
  const healedRef = useRef<number | undefined>(undefined);

  // fetch the incident's blast-radius subgraph when the active incident changes
  useEffect(() => {
    if (!active) {
      setSubgraph(null);
      return;
    }
    let cancelled = false;
    api.incidentSubgraph(active.seq).then((sg) => { if (!cancelled) setSubgraph(sg); }).catch(() => {});
    return () => { cancelled = true; };
  }, [active?.seq]);

  // reset the walk on a new incident
  useEffect(() => {
    if (!active) {
      seqRef.current = undefined;
      setPhase(0); setStep(0); setVStep(0); setPlaying(false);
      return;
    }
    if (seqRef.current !== active.seq) {
      seqRef.current = active.seq;
      setRejected(undefined);
      setPhase(0); setStep(0); setVStep(0); setPlaying(true);
    }
  }, [active?.seq]);

  // auto-advance: cascade node-by-node, investigate step-by-step, pause at Propose
  useEffect(() => {
    if (!active || !playing || !subgraph) return;
    const dwell = phase === 1 ? 380 : phase === 3 ? 520 : 1100;
    const t = setTimeout(() => {
      if (phase === 1 && step < subgraph.cascade_order.length - 1) setStep((s) => s + 1);
      else if (phase === 3 && vStep < VULCAN_STEPS.length) setVStep((v) => v + 1);
      else if (phase < 4) { setPhase((p) => p + 1); setStep(0); }
      else setPlaying(false);
    }, dwell);
    return () => clearTimeout(t);
  }, [active?.seq, subgraph, playing, phase, step, vStep]);

  const phaseKey = PHASES[phase].key;
  const isRejected = active && rejected === active.seq;
  const safe = active ? SAFE.has(active.kind) : false;
  const remediation = active ? REMEDIATION[active.kind] ?? "manual intervention" : "";
  const rootId = subgraph?.target;

  const revealedSet = useMemo(
    () => revealedNodes(isRejected ? null : subgraph, phaseKey, step),
    [subgraph, phaseKey, step, isRejected],
  );
  const highlightNode =
    phaseKey === "investigate" && subgraph
      ? subgraph.cascade_order[Math.min(vStep, subgraph.cascade_order.length - 1)] ?? null
      : null;

  const approve = () => {
    if (active && healedRef.current !== active.seq) {
      healedRef.current = active.seq;
      onHeal?.(active.seq);
    }
    setPhase(5);
  };

  const phaseDetail = (p: Phase): string => {
    if (!active || !subgraph) return "";
    switch (p) {
      case "inject": return `${active.kind} at ${active.target}`;
      case "cascade": return `${subgraph.cascade_order.length} nodes in blast radius`;
      case "collapse": return `${subgraph.nodes.length} elements affected`;
      case "investigate": return `Vulcan tracing root cause → ${rootId}`;
      case "propose": return `${remediation} — ${safe ? "safe" : "SIS/gas, needs approval"}`;
      case "resolution": return isRejected ? "rejected — incident open" : "resolved";
    }
  };

  return (
    <div className="investigate" data-testid="investigate">
      <div className="inv-layout">
        {agent ? (
          <AgentPanel
            agent={agent}
            onRefresh={onRefresh}
            active={isRejected ? undefined : active}
            phase={phase}
            vStep={vStep}
            rootId={rootId}
            safe={safe}
            remediation={remediation}
            onApprove={approve}
            onReject={() => { if (active) { setRejected(active.seq); setPlaying(false); } }}
          />
        ) : (
          <aside className="inv-agent" data-testid="inv-agent">
            <div className="agent-head"><span className="agent-title">🔒 VULCAN AGENT</span></div>
          </aside>
        )}

        <div className="inv-main">
          <div className="inv-phases" data-testid="inv-phases">
            {PHASES.map((p, i) => (
              <span
                key={p.key}
                className={`inv-phase${i === phase ? " active" : ""}${i < phase ? " done" : ""}`}
                onClick={() => { if (active) { setPlaying(false); setPhase(i); setStep(0); } }}
              >
                <b>{p.key === "resolution" && isRejected ? "✕" : p.icon}</b> {p.label}
              </span>
            ))}
          </div>

          <div className="sg-wrap" data-testid="sg-wrap">
            <SubgraphCanvas
              subgraph={isRejected ? null : subgraph}
              phase={phaseKey}
              revealedSet={revealedSet}
              highlightNode={highlightNode}
              phaseLabel={PHASES[phase].label}
              phaseDetail={phaseDetail(phaseKey)}
            />
            {!active && <div className="sg-empty" data-testid="sg-empty">No active incident — inject a fault to investigate.</div>}
          </div>

          {active && (
            <div className="inv-foot" data-testid="inv-caption">
              <span className="inv-transport">
                <button onClick={() => setPlaying((v) => !v)} data-testid="inv-play">{playing ? "⏸" : "▶"}</button>
                <button
                  data-testid="inv-step"
                  onClick={() => {
                    if (phase === 1 && subgraph && step < subgraph.cascade_order.length - 1) setStep((s) => s + 1);
                    else setPhase((p) => Math.min(p + 1, PHASES.length - 1));
                  }}
                >⏭ Step</button>
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
