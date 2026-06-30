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

export interface HealEvent {
  id: number;
  incident_seq: number;
  kind: string;
  target: string;
  action: string;
  auto: boolean;
  approved: boolean | null;
  countdown: number;
}

export interface AgentStatus {
  running: boolean;
  state: string;
  mode: string;
  events: HealEvent[];
  pending: HealEvent[];
}

export interface State {
  tick: number;
  plant_minutes: number;
  plant_minutes_per_tick: number;
  flagged: string[];
  agent: { running: boolean; state: string; mode: string; pending: number };
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

export interface GraphNode {
  id: string;
  name: string;
  kind: string;
  section: string;
  status: string;
}

export interface GraphEdge {
  src: string;
  dst: string;
  kind: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface NetNode {
  id: string;
  type: string;
  section: string;
  unit?: string;
  level: number;
  state: string;
  in_alarm: boolean;
  in_trip: boolean;
  value: number | null;
}

export interface NetGraph {
  nodes: NetNode[];
  edges: { src: string; dst: string }[];
}

export interface FleetNode {
  tag: string;
  type: string;
  section: string;
  unit: string;
  sim_state: string;
  registry: string; // active | stale | absent
  reachable: boolean;
  problem: string | null;
}

export interface FleetData {
  registry: string; // connected | disconnected | unreachable
  nodes: FleetNode[];
  summary: { total: number; failed: number; stale: number; unreachable: number };
}
