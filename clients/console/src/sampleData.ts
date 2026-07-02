// Demo fleet shown ONLY when VITE_USE_SAMPLE_DATA=true (an explicit dev
// flag — never a fallback, §0.11). Shape matches contracts/
// control-plane.openapi.yaml FleetView, including a populated `workgroup`
// (which the v2 Registry still serves as null) so the grouping UI is
// visible in demos before Sprint B6 assignment ships.
import type { FleetView } from './fleet';
import type { NodesView } from './nodes';

const MINUTES = 60_000;

export function buildSampleFleet(nowMs: number): FleetView {
  return {
    generatedAt: new Date(nowMs).toISOString(),
    devices: [
      {
        id: 'dev-front-desk',
        label: 'Front desk PC',
        enrollment: 'active',
        connection: 'online',
        lastSeen: new Date(nowMs - MINUTES / 2).toISOString(),
        address: 'front-desk.local:8444',
        capabilities: ['llm'],
        powerProfile: { name: 'laptop', cpus: 2, memory: '2g', gpus: null },
        workgroup: { workgroupId: 'wg_front_office_demo01', name: 'Front office' },
      },
      {
        id: 'dev-workshop-server',
        label: 'Workshop server',
        enrollment: 'active',
        connection: 'stale',
        lastSeen: new Date(nowMs - 90 * MINUTES).toISOString(),
        address: 'workshop.local:8444',
        capabilities: ['gpu', 'llm'],
        powerProfile: { name: 'gpu-server', cpus: 16, memory: '32g', gpus: 'all' },
        workgroup: { workgroupId: 'wg_back_office_demo01', name: 'Back office' },
      },
      {
        id: 'dev-owners-laptop',
        label: "Owner's laptop",
        enrollment: 'pending',
        connection: 'offline',
        lastSeen: null,
        workgroup: null,
      },
    ],
  };
}

// Demo node facts for the Fleet tree (Sprint S4). Shown ONLY in explicit
// sample mode (§0.11) so the node tree renders with no backend. Shape matches
// contracts/control-plane.openapi.yaml NodesView / NodeFacts — a GPU node
// (gx10) and a small no-GPU node so both branches of the tree are visible.
export function buildSampleNodes(nowMs: number): NodesView {
  const gatheredAt = new Date(nowMs - 5 * MINUTES).toISOString();
  return {
    generatedAt: new Date(nowMs).toISOString(),
    nodes: [
      {
        nodeId: 'gx10',
        cpu: { model: 'NVIDIA Grace GB10', arch: 'aarch64', cores: 20, vcpus: 20 },
        memory: { totalMb: 131072 },
        gpu: { model: 'NVIDIA GB10', memoryMb: 131072 },
        storage: [
          { device: 'nvme0n1', sizeGb: 1024 },
          { device: 'nvme1n1', sizeGb: 4096 },
        ],
        networking: [
          { iface: 'enp1s0', ipv4: '192.168.1.20', speedMbps: 10000 },
          { iface: 'wlan0', ipv4: null, speedMbps: null },
        ],
        gatheredAt,
      },
      {
        nodeId: 'snoopy',
        cpu: { model: 'Intel Core i5-8259U', arch: 'x86_64', cores: 4, vcpus: 8 },
        memory: { totalMb: 16384 },
        gpu: null,
        storage: [{ device: 'sda', sizeGb: 512 }],
        networking: [{ iface: 'eth0', ipv4: '192.168.1.31', speedMbps: 1000 }],
        gatheredAt,
      },
      {
        nodeId: 'front-desk',
        cpu: { model: 'AMD Ryzen 5 5600G', arch: 'x86_64', cores: 6, vcpus: 12 },
        memory: { totalMb: 8192 },
        gpu: null,
        storage: [{ device: 'nvme0n1', sizeGb: 256 }],
        networking: [{ iface: 'enp2s0', ipv4: '192.168.1.15', speedMbps: 1000 }],
        gatheredAt,
      },
    ],
  };
}
