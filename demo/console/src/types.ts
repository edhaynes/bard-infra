// Mirrors the orchestrator API JSON (refinery/api.py).

export interface ElementView {
  tag: string;
  agent_id: string;
  type: string;
  signal: string;
  unit: string;
  section: string;
  process_unit: string;
  value: number;
  setpoint: number | null;
  state: string;
  in_alarm: boolean;
  in_trip: boolean;
}

export interface UnitView {
  id: string;
  name: string;
  kind: string;
  status: string;
  elements: ElementView[];
}

export interface SectionView {
  id: string;
  name: string;
  bringup_order: number;
  network: ElementView[];
  units: UnitView[];
}

export interface Incident {
  seq: number;
  kind: string;
  target: string;
  description: string;
  affected: string[];
  resolved: boolean;
}

export interface SeqStatus {
  mode: string;
  units_running: number;
  units_total: number;
  blocked: { unit: string; reason: string } | null;
}

export interface State {
  tick: number;
  signals: {
    elements_total: number;
    by_state: Record<string, number>;
    alarms: string[];
    trips: string[];
    sections: Record<string, { name: string; status: string; running: number; total: number; alarms: number }>;
    units_total: number;
    units_running: number;
  };
  sequencer: SeqStatus;
  incidents: Incident[];
}

export type FaultKinds = Record<string, { label: string; target: string }>;
