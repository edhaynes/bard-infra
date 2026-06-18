// API client for the demo console. Talks to the Registry (/agents, /pool,
// /schedule) and Router (/v1/message). When no live backend is configured it
// falls back to SEED data so the visual renders standalone.
//
// Live wiring: set VITE_REGISTRY_BASE, VITE_ROUTER_BASE, VITE_TOKEN (a JWT the
// serve-mode backend accepts). Plain-HTTP + CORS on localhost for the demo.

import type { AgentRecord, JobResult, PoolCapacity } from "./types";

const REGISTRY = import.meta.env.VITE_REGISTRY_BASE ?? "";
const ROUTER = import.meta.env.VITE_ROUTER_BASE ?? "";
const TOKEN = import.meta.env.VITE_TOKEN ?? "";
const LIVE = REGISTRY !== "" && ROUTER !== "";

const SEED_FLEET: AgentRecord[] = [
  { agentId: "gpu-workstation", address: "10.0.0.5:8451", capabilities: ["gpu", "llm"], powerProfile: { name: "gpu-workstation", cpus: 16, memory: "64g", gpus: "all" } },
  { agentId: "dev-laptop", address: "10.0.0.6:8452", capabilities: ["llm"], powerProfile: { name: "dev-laptop", cpus: 8, memory: "16g", gpus: null } },
  { agentId: "storage-node", address: "10.0.0.7:8453", capabilities: ["storage"], powerProfile: { name: "storage-node", cpus: 4, memory: "8g", gpus: null } },
  { agentId: "edge-box", address: "10.0.0.8:8454", capabilities: ["llm"], powerProfile: { name: "edge-box", cpus: 4, memory: "4g", gpus: null } },
];

const SEED_POOL: PoolCapacity = { nodes: 4, cpus: 32, memoryBytes: 92 * 1024 ** 3, gpuNodes: 1 };

function auth(): HeadersInit {
  return TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
}

export async function fetchFleet(): Promise<AgentRecord[]> {
  if (!LIVE) return structuredClone(SEED_FLEET);
  const r = await fetch(`${REGISTRY}/agents`, { headers: auth() });
  return (await r.json()) as AgentRecord[];
}

export async function fetchPool(): Promise<PoolCapacity> {
  if (!LIVE) return structuredClone(SEED_POOL);
  const r = await fetch(`${REGISTRY}/pool`, { headers: auth() });
  return (await r.json()) as PoolCapacity;
}

export async function schedule(gpu: boolean): Promise<AgentRecord> {
  if (!LIVE) return SEED_FLEET.find((n) => (gpu ? n.powerProfile?.gpus : true)) ?? SEED_FLEET[0];
  const r = await fetch(`${REGISTRY}/schedule?gpu=${gpu}`, { headers: auth() });
  return (await r.json()) as AgentRecord;
}

export async function runJob(agentId: string, content: string): Promise<JobResult> {
  if (!LIVE) {
    await new Promise((res) => setTimeout(res, 600));
    return { agentId, content: `(demo) ${content.slice(0, 60)} … served from ${agentId}.` };
  }
  const r = await fetch(`${ROUTER}/v1/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: `job-${Date.now()}`,
      type: "text",
      content,
      metadata: { targetAgent: agentId, authToken: TOKEN },
    }),
  });
  const body = (await r.json()) as { metadata?: { agentId?: string }; content?: string };
  return { agentId: body.metadata?.agentId ?? agentId, content: body.content ?? "" };
}

export const isLive = LIVE;
