import type { AgentStatus, FaultKinds, Incident, NetGraph, SectionView, State } from "./types";

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
};
