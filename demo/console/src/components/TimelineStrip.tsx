import type { State } from "../types";

// Bring-up order — the timeline reads left→right as the plant comes up (reverse on down).
const SECTION_ORDER = ["S4", "S1", "S3", "S2", "S5"];

const MODE_LABEL: Record<string, string> = {
  idle: "IDLE",
  bringing_up: "▲ BRINGING UP",
  bringing_down: "▼ BRINGING DOWN",
};

function fmtPlant(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d ${h % 24}h ${m}m`;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

export function TimelineStrip({ state }: { state: State }) {
  const { sequencer: seq, signals: s } = state;
  return (
    <footer className="timeline" data-testid="timeline">
      <div className="tl-left">
        <span className={`tl-mode mode-${seq.mode}`}>{MODE_LABEL[seq.mode] ?? seq.mode}</span>
        <span className="tl-clock" data-testid="plant-clock">
          plant&nbsp;{fmtPlant(state.plant_minutes)}
        </span>
        <span className="tl-comp">
          1s = {state.plant_minutes_per_tick}min · t{state.tick}
        </span>
      </div>
      <div className="tl-track">
        {SECTION_ORDER.map((id) => {
          const sec = s.sections[id];
          const fill = sec && sec.total ? (100 * sec.running) / sec.total : 0;
          return (
            <div
              key={id}
              className={`tl-seg s-${sec?.status ?? "offline"}`}
              data-testid={`tl-${id}`}
              title={sec ? `${sec.name}: ${sec.status} (${sec.running}/${sec.total})` : id}
            >
              <span className="tl-seg-id">{id}</span>
              <span className="tl-seg-bar">
                <i style={{ width: `${fill}%` }} />
              </span>
            </div>
          );
        })}
      </div>
      <div className="tl-right">
        <span className="tl-units">
          {seq.units_running}/{seq.units_total} units
        </span>
        {state.flagged.length > 0 && (
          <span className="tl-flag" data-testid="tl-flag">
            ⚠ {state.flagged.length} off-kilter
          </span>
        )}
      </div>
    </footer>
  );
}
