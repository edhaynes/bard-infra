// Demo fleet shown ONLY when VITE_USE_SAMPLE_DATA=true (an explicit dev
// flag — never a fallback, §0.11). Shape matches contracts/
// control-plane.openapi.yaml FleetView, including a populated `workgroup`
// (which the v2 Registry still serves as null) so the grouping UI is
// visible in demos before Sprint B6 assignment ships.
import type { FleetView } from './fleet';

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
