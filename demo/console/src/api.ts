import type {
  AgentStatus,
  FaultKinds,
  FleetData,
  Incident,
  NetGraph,
  SectionView,
  State,
  SubgraphSlice,
} from "./types";

const BASE = (import.meta.env.VITE_ORCH_BASE as string | undefined) ?? "http://127.0.0.1:7090";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  state: () => get<State>("/state"),
  sections: () => get<SectionView[]>("/sections"),
  faults: () => get<FaultKinds>("/faults"),
  netgraph: () => get<NetGraph>("/netgraph"),
  fleet: () => get<FleetData>("/fleet"),
  incidentSubgraph: (seq: number) => get<SubgraphSlice>(`/incident_subgraph/${seq}`),
  bringup: () => post("/bringup"),
  bringdown: () => post("/bringdown"),
  reset: () => post("/reset"),
  inject: (kind: string, target: string) => post<Incident>("/inject", { kind, target }),
  resolve: (seq: number) => post<Incident>(`/resolve/${seq}`),
  agentStatus: () => get<AgentStatus>("/agent/status"),
  agentStart: () => post<AgentStatus>("/agent/start"),
  agentStop: () => post<AgentStatus>("/agent/stop"),
  agentMode: (mode: string) => post<AgentStatus>("/agent/mode", { mode }),
  agentApprove: (id: number) => post("/agent/approve/" + id),
  agentReject: (id: number) => post("/agent/reject/" + id),
  agentSetConfig: (provider: string, model: string, apiKey?: string, baseUrl?: string) =>
    post("/agent/config", { provider, model, api_key: apiKey, base_url: baseUrl }),
  agentPrompt: () => get<{ prompt: string }>("/agent/prompt"),
  agentSetPrompt: (prompt: string) => post<{ prompt: string }>("/agent/prompt", { prompt }),
  agentPolishPrompt: () => post<{ prompt: string }>("/agent/prompt/polish"),
};
