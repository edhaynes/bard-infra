import type { SeqStatus } from "../types";

interface Props {
  seq: SeqStatus;
  tick: number;
  onBringUp: () => void;
  onBringDown: () => void;
  onReset: () => void;
}

const MODE_LABEL: Record<string, string> = {
  idle: "IDLE",
  bringing_up: "BRINGING UP",
  bringing_down: "BRINGING DOWN",
};

export function TopBar({ seq, tick, onBringUp, onBringDown, onReset }: Props) {
  const busy = seq.mode !== "idle";
  return (
    <header className="topbar" data-testid="topbar">
      <div className="brand">
        <span className="brand-mark">▮▮▮</span> REFINERY OPS
        <span className="brand-sub">bard-infra · Baytown (modeled)</span>
      </div>
      <div className="ops">
        <button data-testid="btn-bringup" disabled={busy} onClick={onBringUp}>
          ▲ Bring up
        </button>
        <button data-testid="btn-bringdown" disabled={busy} onClick={onBringDown}>
          ▼ Bring down
        </button>
        <button data-testid="btn-reset" className="ghost" onClick={onReset}>
          ⟲ Reset
        </button>
      </div>
      <div className="status-pills">
        <span className={`pill mode-${seq.mode}`} data-testid="mode">
          {MODE_LABEL[seq.mode] ?? seq.mode}
        </span>
        {seq.blocked && (
          <span className="pill warn" data-testid="blocked">
            {seq.blocked.unit}: {seq.blocked.reason}
          </span>
        )}
        <span className="clock">t{tick}</span>
      </div>
    </header>
  );
}
