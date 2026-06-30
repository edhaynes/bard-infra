import { useMemo, useState } from "react";

import type { FleetData, FleetNode } from "../types";

const SECTION_NAMES: Record<string, string> = {
  S4: "Utilities & Offsites",
  S1: "Crude & Vacuum",
  S3: "Treating & Reforming",
  S2: "Conversion",
  S5: "Tank Farm & Blending",
};
const ORDER = ["S4", "S1", "S3", "S2", "S5"];

type Filter = "all" | "failed" | "conn";

const isFailed = (n: FleetNode) =>
  n.sim_state === "tripped" || n.sim_state === "down" || n.registry === "stale";
const regBadge = (r: string) => (r === "active" ? "●" : r === "stale" ? "○" : "·");

function NodeRow({ n }: { n: FleetNode }) {
  return (
    <div className={`tree-row node s-${n.sim_state}`} data-testid={`node-${n.tag}`}>
      <span className={`dot s-${n.sim_state}`} />
      <span className="node-tag">{n.tag}</span>
      <span className="node-type">{n.type}</span>
      <span className={`reg-badge reg-${n.registry}`} title={`Registry ${n.registry}`}>
        {regBadge(n.registry)} {n.registry}
      </span>
      {n.reachable ? (
        <span className="conn-ok">✓ reachable</span>
      ) : (
        <span className="conn-bad" title={n.problem ?? ""}>
          ⚠ {n.problem}
        </span>
      )}
    </div>
  );
}

export function FleetView({ fleet }: { fleet: FleetData | null }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(ORDER));
  const [filter, setFilter] = useState<Filter>("all");
  const toggle = (id: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const grouped = useMemo(() => {
    if (!fleet) return null;
    const pass = (n: FleetNode) =>
      filter === "all" || (filter === "failed" && isFailed(n)) || (filter === "conn" && !n.reachable);
    const sections = new Map<string, { net: FleetNode[]; units: Map<string, FleetNode[]> }>();
    for (const n of fleet.nodes) {
      if (!pass(n)) continue;
      const sec = sections.get(n.section) ?? {
        net: [] as FleetNode[],
        units: new Map<string, FleetNode[]>(),
      };
      if (n.unit.endsWith("-net")) sec.net.push(n);
      else {
        const u = sec.units.get(n.unit) ?? [];
        u.push(n);
        sec.units.set(n.unit, u);
      }
      sections.set(n.section, sec);
    }
    return sections;
  }, [fleet, filter]);

  if (!fleet || !grouped) return <div className="loading">Loading fleet…</div>;
  const sum = fleet.summary;
  const autoOpen = filter !== "all";

  return (
    <div className="fleet" data-testid="fleet">
      <div className="fleet-head">
        <span className="fleet-title">FLEET — {fleet.nodes.length} nodes</span>
        <span className={`fleet-reg reg-${fleet.registry}`} data-testid="fleet-registry">
          bard-infra Registry: {fleet.registry}
        </span>
        <span className="fleet-sum">
          <b>{sum.total}</b> total · <b className="bad">{sum.failed}</b> failed ·{" "}
          <b>{sum.stale}</b> stale · <b className="bad">{sum.unreachable}</b> unreachable
        </span>
        <span className="fleet-filters">
          {(["all", "failed", "conn"] as Filter[]).map((f) => (
            <button
              key={f}
              className={filter === f ? "ff active" : "ff"}
              data-testid={`filter-${f}`}
              onClick={() => setFilter(f)}
            >
              {f === "all" ? "All" : f === "failed" ? "Failed" : "Connectivity"}
            </button>
          ))}
        </span>
      </div>

      <div className="fleet-tree" data-testid="fleet-tree">
        {ORDER.filter((sid) => grouped.has(sid)).map((sid) => {
          const sec = grouped.get(sid)!;
          const open = expanded.has(sid) || autoOpen;
          const secNodes = [...sec.net, ...[...sec.units.values()].flat()];
          const failed = secNodes.filter(isFailed).length;
          const unreach = secNodes.filter((n) => !n.reachable).length;
          return (
            <div key={sid} className="tree-section">
              <div className="tree-row sec" onClick={() => toggle(sid)} data-testid={`sec-${sid}`}>
                <span className="caret">{open ? "▾" : "▸"}</span>
                <b>{sid}</b> {SECTION_NAMES[sid]}
                <span className="row-badges">
                  {secNodes.length} nodes
                  {failed > 0 && <em className="bad"> · {failed} failed</em>}
                  {unreach > 0 && <em className="bad"> · {unreach} unreachable</em>}
                </span>
              </div>
              {open && (
                <>
                  {sec.net.length > 0 && (
                    <div className="tree-group">
                      <div className="tree-row group">network gear</div>
                      {sec.net.map((n) => (
                        <NodeRow key={n.tag} n={n} />
                      ))}
                    </div>
                  )}
                  {[...sec.units.entries()].map(([uid, nodes]) => {
                    const uopen = expanded.has(uid) || autoOpen;
                    const ufail = nodes.filter(isFailed).length;
                    return (
                      <div key={uid} className="tree-group">
                        <div
                          className="tree-row unit"
                          onClick={() => toggle(uid)}
                          data-testid={`unit-${uid}`}
                        >
                          <span className="caret">{uopen ? "▾" : "▸"}</span> {uid}
                          <span className="unit-count">{nodes.length}</span>
                          {ufail > 0 && <em className="bad">· {ufail} failed</em>}
                        </div>
                        {uopen && nodes.map((n) => <NodeRow key={n.tag} n={n} />)}
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          );
        })}
        {grouped.size === 0 && <div className="fleet-empty">No nodes match this filter.</div>}
      </div>
    </div>
  );
}
