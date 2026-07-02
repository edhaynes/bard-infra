// Node hardware facts types + pure presentation helpers (Sprint S4,
// feature #91). Mirrors contracts/control-plane.openapi.yaml `GET /nodes`
// (NodesView / NodeFacts) — kept in sync by hand like src/fleet.ts; a
// generator is a follow-up. All functions here are pure so rendering stays
// trivially testable and the Playwright suite only asserts structure (§14).
//
// Plain, friendly labels (§1): the reader is a small-business owner. These
// ARE hardware facts, so we keep the real names (CPU model, GPU, disk sizes)
// but format them into human-readable strings — "128 GB", "1 TB", "None".

/** One physical/virtual disk reported by ansible_devices (real disks only). */
export interface NodeStorage {
  device: string;
  sizeGb: number;
}

/** One network interface reported by ansible_interfaces (virtual/loopback
 *  filtered out upstream in the projector). */
export interface NodeNetworking {
  iface: string;
  ipv4: string | null;
  speedMbps: number | null;
}

/** GPU facts filled by the nvidia-smi custom fact; null = the node has none. */
export interface NodeGpu {
  model: string;
  memoryMb: number;
}

/** contracts/control-plane.openapi.yaml NodeFacts. */
export interface NodeFacts {
  nodeId: string;
  cpu: {
    model: string;
    arch: string;
    cores: number;
    vcpus: number;
  };
  memory: {
    totalMb: number;
  };
  gpu: NodeGpu | null;
  storage: NodeStorage[];
  networking: NodeNetworking[];
  gatheredAt: string;
}

/** contracts/control-plane.openapi.yaml NodesView. */
export interface NodesView {
  nodes: NodeFacts[];
  generatedAt: string;
}

// --- formatting helpers (all pure) -----------------------------------------

const MB_PER_GB = 1024;
const GB_PER_TB = 1024;

/** Trim a trailing ".0" so whole numbers read cleanly ("128" not "128.0"). */
function trimZero(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/**
 * Memory in megabytes → a friendly string. Under 1 GB stays in MB
 * ("512 MB"); 1 GB and up rolls to GB ("2 GB", "128 GB", "1.5 GB").
 */
export function formatMemoryMb(totalMb: number): string {
  if (totalMb < MB_PER_GB) return `${Math.round(totalMb)} MB`;
  return `${trimZero(totalMb / MB_PER_GB)} GB`;
}

/**
 * Disk size in gigabytes → a friendly string. Under 1 TB stays in GB
 * ("512 GB"); 1 TB and up rolls to TB ("1 TB", "2 TB", "1.9 TB").
 */
export function formatStorageGb(sizeGb: number): string {
  if (sizeGb < GB_PER_TB) return `${trimZero(sizeGb)} GB`;
  return `${trimZero(sizeGb / GB_PER_TB)} TB`;
}

/** GPU label — the model plus its memory, or "None" when the node has none. */
export function gpuLabel(gpu: NodeGpu | null): string {
  if (gpu === null) return 'None';
  return `${gpu.model} (${formatMemoryMb(gpu.memoryMb)})`;
}

/** One disk, one line: "nvme0n1 — 1 TB". */
export function storageLabel(disk: NodeStorage): string {
  return `${disk.device} — ${formatStorageGb(disk.sizeGb)}`;
}

/**
 * One network interface, one line. No address / unknown speed degrade to
 * plain words rather than showing "null".
 */
export function networkingLabel(net: NodeNetworking): string {
  const address = net.ipv4 ?? 'No address';
  const speed = net.speedMbps === null ? 'Speed unknown' : `${net.speedMbps} Mbps`;
  return `${net.iface} — ${address} — ${speed}`;
}

/**
 * The collapsed-row one-liner: cores, memory, and GPU presence at a glance
 * so the owner can read the fleet without expanding every node.
 */
export function nodeSummary(node: NodeFacts): string {
  const cores = `${node.cpu.cores} ${node.cpu.cores === 1 ? 'core' : 'cores'}`;
  const memory = formatMemoryMb(node.memory.totalMb);
  const gpu = node.gpu === null ? 'No graphics card' : `${node.gpu.model} graphics`;
  return `${cores} · ${memory} · ${gpu}`;
}

// --- fleet rollup (pure) ----------------------------------------------------

/** Fleet-wide totals for the summary strip (feature #91 "one pane to see the
 *  fleet"). Facts carry no liveness, so this is capacity, not health. */
export interface FleetSummary {
  nodeCount: number;
  /** Nodes that report a GPU. */
  gpuCount: number;
  totalVcpus: number;
  totalMemoryMb: number;
  totalStorageGb: number;
}

/** Sum the fleet's capacity across every node. Pure; empty fleet → all zeros. */
export function fleetSummary(nodes: NodeFacts[]): FleetSummary {
  return nodes.reduce<FleetSummary>(
    (acc, node) => ({
      nodeCount: acc.nodeCount + 1,
      gpuCount: acc.gpuCount + (node.gpu === null ? 0 : 1),
      totalVcpus: acc.totalVcpus + node.cpu.vcpus,
      totalMemoryMb: acc.totalMemoryMb + node.memory.totalMb,
      totalStorageGb:
        acc.totalStorageGb + node.storage.reduce((sum, disk) => sum + disk.sizeGb, 0),
    }),
    { nodeCount: 0, gpuCount: 0, totalVcpus: 0, totalMemoryMb: 0, totalStorageGb: 0 },
  );
}

// --- tree building (pure) ---------------------------------------------------

/**
 * Order the nodes for display: alphabetical by node id. Returns a new array
 * (never mutates the input) so callers can render deterministically. This is
 * the "tree" the console renders — one expandable branch per node.
 */
export function buildNodeTree(nodes: NodeFacts[]): NodeFacts[] {
  return [...nodes].sort((a, b) => a.nodeId.localeCompare(b.nodeId));
}
