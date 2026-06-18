// Domain types for the Bard stranded-compute demo console.
// Mirror the registry/router contracts (registry.openapi.yaml).

export interface PowerProfile {
  name: string;
  cpus?: number;
  memory?: string;
  gpus?: string | null;
}

export interface AgentRecord {
  agentId: string;
  address: string;
  capabilities?: string[];
  powerProfile?: PowerProfile;
  registeredAt?: string;
}

export interface PoolCapacity {
  nodes: number;
  cpus: number;
  memoryBytes: number;
  gpuNodes: number;
}

export interface JobResult {
  agentId: string;
  content: string;
}
