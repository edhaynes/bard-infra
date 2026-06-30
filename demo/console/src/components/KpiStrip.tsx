import type { State } from "../types";

function Kpi({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className={`kpi-card ${tone ? `s-${tone}` : ""}`}>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

export function KpiStrip({ state }: { state: State }) {
  const s = state.signals;
  const discovered = s.by_state["discovered"] ?? 0;
  const down = (s.by_state["down"] ?? 0) + (s.by_state["tripped"] ?? 0);
  const sectionsUp = Object.values(s.sections).filter((x) => x.status === "running").length;
  return (
    <div className="kpi" data-testid="kpi">
      <Kpi label="Units running" value={`${s.units_running}/${s.units_total}`} tone={s.units_running === s.units_total ? "running" : "partial"} />
      <Kpi label="Sections up" value={`${sectionsUp}/${Object.keys(s.sections).length}`} tone={sectionsUp === 5 ? "running" : "partial"} />
      <Kpi label="Elements" value={s.elements_total} />
      <Kpi label="Discovered" value={discovered} tone="discovered" />
      <Kpi label="Alarms" value={s.alarms.length} tone={s.alarms.length ? "partial" : "running"} />
      <Kpi label="Tripped / down" value={down} tone={down ? "tripped" : "running"} />
    </div>
  );
}
