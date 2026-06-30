import { useState } from "react";

import type { FaultKinds, Incident, SectionView } from "../types";

interface Props {
  incidents: Incident[];
  faults: FaultKinds;
  sections: SectionView[];
  onInject: (kind: string, target: string) => void;
  onResolve: (seq: number) => void;
}

// Build the target option list for a chosen fault kind from the live topology.
function targetsFor(kind: string, faults: FaultKinds, sections: SectionView[]): string[] {
  const t = faults[kind]?.target;
  if (t === "section") return sections.map((s) => s.id);
  if (t === "unit") return sections.flatMap((s) => s.units.map((u) => u.id));
  if (t === "pump")
    return sections.flatMap((s) => s.units.flatMap((u) => u.elements.filter((e) => e.type === "pump").map((e) => e.tag)));
  // element
  return sections.flatMap((s) => s.units.flatMap((u) => u.elements.map((e) => e.tag)));
}

export function SidePanel({ incidents, faults, sections, onInject, onResolve }: Props) {
  const kinds = Object.keys(faults);
  const [kind, setKind] = useState("");
  const [target, setTarget] = useState("");
  const effKind = kind || kinds[0] || "";
  const targets = effKind ? targetsFor(effKind, faults, sections) : [];
  const open = incidents.filter((i) => !i.resolved);

  return (
    <>
      <div className="panel">
        <div className="panel-head">Inject fault</div>
        <div className="inject" data-testid="inject">
          <select aria-label="fault kind" value={effKind} onChange={(e) => { setKind(e.target.value); setTarget(""); }}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {faults[k].label}
              </option>
            ))}
          </select>
          <select aria-label="fault target" value={target || targets[0] || ""} onChange={(e) => setTarget(e.target.value)}>
            {targets.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <button
            data-testid="btn-inject"
            disabled={!effKind || targets.length === 0}
            onClick={() => onInject(effKind, target || targets[0])}
          >
            Inject
          </button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          Incidents <span className="count">{open.length}</span>
        </div>
        <ul className="incidents" data-testid="incidents">
          {open.length === 0 && <li className="empty">No open incidents</li>}
          {open.map((i) => (
            <li key={i.seq} className="incident s-tripped" data-testid={`incident-${i.seq}`}>
              <div className="incident-desc">{i.description}</div>
              <div className="incident-foot">
                <span className="incident-affected">{i.affected.length} affected</span>
                <button className="ghost" onClick={() => onResolve(i.seq)}>
                  Resolve
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
