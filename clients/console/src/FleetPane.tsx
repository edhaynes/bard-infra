// Fleet pane — the node tree (Sprint S4, feature #91). Every registered node
// is an expandable branch; expanding it reveals that node's real hardware
// facts (CPU, memory, GPU, storage, networking) gathered by ansible and served
// at GET /nodes. Same load / refresh / error / sample pattern as DevicesPane
// in App.tsx; the API is the only source in api-mode and buildSampleNodes is
// the ONLY source in explicit sample mode (§0.11 — never a silent fallback).
//
// Plain, friendly labels (§1) — these are hardware facts, so we keep the real
// names but format them for a non-technical owner. Structural className hooks
// (.fleet-tree, .node-row, .node-facts, .fact-*) exist for the Playwright
// suite; visual correctness is Eddie's screenshot sign-off (§14).
import { useCallback, useEffect, useState } from 'react';
import { ControlPlaneClient } from './api';
import { loadConfig } from './config';
import type { ConsoleConfig } from './config';
import {
  buildNodeTree,
  formatMemoryMb,
  gpuLabel,
  networkingLabel,
  nodeSummary,
  storageLabel,
} from './nodes';
import type { NodeFacts, NodesView } from './nodes';
import { buildSampleNodes } from './sampleData';
import { s } from './styles';

const config: ConsoleConfig = loadConfig(import.meta.env as Record<string, string | undefined>);

// The facts payload is heavy and changes slowly (hardware rarely moves), so it
// refreshes far less often than the device list.
const REFRESH_MS = 60_000;

export function FleetPane({ client }: { client: ControlPlaneClient | null }) {
  const [view, setView] = useState<NodesView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const load = useCallback(async () => {
    if (client === null) return;
    try {
      const nodes = await client.fetchNodes();
      setView(nodes);
      setError(null);
    } catch (cause) {
      // Fail loudly: surface the message, keep the last good tree on screen,
      // and NEVER swap in sample data (§0.11).
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [client]);

  useEffect(() => {
    if (client === null) {
      // Explicit demo mode only — loadConfig never routes here as a fallback.
      setView(buildSampleNodes(Date.now()));
      return;
    }
    let cancelled = false;
    const tick = async () => {
      if (!cancelled) await load();
    };
    void tick();
    const timer = setInterval(() => void tick(), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [client, load]);

  const toggle = useCallback((nodeId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  const nodes = view ? buildNodeTree(view.nodes) : [];

  return (
    <div>
      <h1 style={s.h1}>Fleet</h1>
      <p style={s.dim}>
        Every machine in your fleet and what is inside it. Open a machine to see its parts.
      </p>
      {config.mode === 'sample' && (
        <div style={s.sampleBanner} className="sample-banner">
          Showing sample data (demo mode). These are not your real machines.
        </div>
      )}
      {error !== null && (
        <div style={s.errorBanner} className="fetch-error" role="alert">
          <div style={s.errorTitle}>Could not load your machines</div>
          <p style={s.errorText}>{error}</p>
        </div>
      )}
      {view === null && error === null && (
        <p style={s.dim} className="loading">
          Checking your machines…
        </p>
      )}
      {view !== null && nodes.length === 0 && (
        <p style={s.dim} className="empty-fleet">
          No machine details yet. Once a machine reports in, its parts will appear here.
        </p>
      )}
      <div style={s.fleetTree} className="fleet-tree">
        {nodes.map((node) => (
          <NodeRow
            key={node.nodeId}
            node={node}
            expanded={expanded.has(node.nodeId)}
            onToggle={() => toggle(node.nodeId)}
          />
        ))}
      </div>
    </div>
  );
}

function NodeRow({
  node,
  expanded,
  onToggle,
}: {
  node: NodeFacts;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      style={s.card}
      className={`node-row${expanded ? ' node-expanded' : ''}`}
      data-node-id={node.nodeId}
    >
      <button
        style={s.nodeToggle}
        className="node-toggle"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span style={s.nodeToggleCaret} className="node-caret" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
        <span style={s.nodeName} className="node-name">
          {node.nodeId}
        </span>
        <span style={s.nodeSummary} className="node-summary">
          {nodeSummary(node)}
        </span>
      </button>
      {expanded && (
        <div style={s.nodeFacts} className="node-facts">
          <Fact className="fact-cpu" label="Processor">
            <div style={s.factValue}>{node.cpu.model}</div>
            <div style={s.factSub}>
              {node.cpu.arch} · {node.cpu.cores} {node.cpu.cores === 1 ? 'core' : 'cores'} ·{' '}
              {node.cpu.vcpus} threads
            </div>
          </Fact>
          <Fact className="fact-memory" label="Memory">
            <div style={s.factValue}>{formatMemoryMb(node.memory.totalMb)}</div>
          </Fact>
          <Fact className="fact-gpu" label="Graphics card">
            <div style={s.factValue}>{gpuLabel(node.gpu)}</div>
          </Fact>
          <Fact className="fact-storage" label="Storage">
            {node.storage.length === 0 ? (
              <div style={s.factValue}>No disks reported</div>
            ) : (
              <ul style={s.factList}>
                {node.storage.map((disk) => (
                  <li key={disk.device} style={s.factListItem} className="fact-storage-item">
                    {storageLabel(disk)}
                  </li>
                ))}
              </ul>
            )}
          </Fact>
          <Fact className="fact-networking" label="Networking">
            {node.networking.length === 0 ? (
              <div style={s.factValue}>No network cards reported</div>
            ) : (
              <ul style={s.factList}>
                {node.networking.map((net) => (
                  <li key={net.iface} style={s.factListItem} className="fact-networking-item">
                    {networkingLabel(net)}
                  </li>
                ))}
              </ul>
            )}
          </Fact>
        </div>
      )}
    </div>
  );
}

function Fact({
  className,
  label,
  children,
}: {
  className: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div style={s.factGroup} className={className}>
      <div style={s.factLabel}>{label}</div>
      {children}
    </div>
  );
}
