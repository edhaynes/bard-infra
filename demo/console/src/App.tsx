import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { FleetView } from "./components/FleetView";
import { InvestigateView } from "./components/InvestigateView";
import { KpiStrip } from "./components/KpiStrip";
import { SectionCard } from "./components/SectionCard";
import { SelfHealPanel } from "./components/SelfHealPanel";
import { SidePanel } from "./components/SidePanel";
import { TimelineStrip } from "./components/TimelineStrip";
import { TopBar, type Tab } from "./components/TopBar";
import type { AgentStatus, FaultKinds, FleetData, NetGraph, SectionView, State } from "./types";

const POLL_MS = 1000;

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [sections, setSections] = useState<SectionView[]>([]);
  const [netgraph, setNetgraph] = useState<NetGraph | null>(null);
  const [agent, setAgent] = useState<AgentStatus | null>(null);
  const [fleet, setFleet] = useState<FleetData | null>(null);
  const [faults, setFaults] = useState<FaultKinds>({});
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [st, secs, ng, ag, fl] = await Promise.all([
        api.state(),
        api.sections(),
        api.netgraph(),
        api.agentStatus(),
        api.fleet(),
      ]);
      setState(st);
      setSections(secs);
      setNetgraph(ng);
      setAgent(ag);
      setFleet(fl);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    api.faults().then(setFaults).catch(() => {});
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const act = useCallback(
    (fn: () => Promise<unknown>) => () => fn().then(refresh).catch((e) => setError(String(e))),
    [refresh],
  );

  if (!state) {
    return (
      <div className="loading" data-testid="loading">
        {error ? `Cannot reach orchestrator: ${error}` : "Connecting to orchestrator…"}
      </div>
    );
  }

  return (
    <div className="shell">
      <TopBar
        seq={state.sequencer}
        tick={state.tick}
        tab={tab}
        onTab={setTab}
        onBringUp={act(api.bringup)}
        onBringDown={act(api.bringdown)}
        onReset={act(api.reset)}
      />
      <KpiStrip state={state} />
      <main className={tab === "overview" ? "plant" : "plant invmode"} data-testid="plant">
        {tab === "overview" &&
          sections.map((s) => (
            <SectionCard
              key={s.id}
              section={s}
              status={state.signals.sections[s.id]?.status ?? "offline"}
            />
          ))}
        {tab === "investigate" && (
          <InvestigateView
            graph={netgraph}
            incidents={state.incidents}
            agent={agent}
            onRefresh={refresh}
            onHeal={(seq) => act(() => api.resolve(seq))()}
          />
        )}
        {tab === "fleet" && <FleetView fleet={fleet} />}
      </main>
      <aside className="side" data-testid="side">
        <SelfHealPanel
          agent={agent}
          onStart={act(api.agentStart)}
          onStop={act(api.agentStop)}
          onMode={(m) => act(() => api.agentMode(m))()}
          onApprove={(id) => act(() => api.agentApprove(id))()}
          onReject={(id) => act(() => api.agentReject(id))()}
        />
        <SidePanel
          incidents={state.incidents}
          faults={faults}
          sections={sections}
          onInject={(k, t) => act(() => api.inject(k, t))()}
          onResolve={(seq) => act(() => api.resolve(seq))()}
        />
      </aside>
      <TimelineStrip state={state} />
      {error && <div className="err-banner" data-testid="error">{error}</div>}
    </div>
  );
}
