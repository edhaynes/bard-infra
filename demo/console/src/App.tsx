import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { KpiStrip } from "./components/KpiStrip";
import { SectionCard } from "./components/SectionCard";
import { SidePanel } from "./components/SidePanel";
import { TopBar } from "./components/TopBar";
import type { FaultKinds, SectionView, State } from "./types";

const POLL_MS = 1000;

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [sections, setSections] = useState<SectionView[]>([]);
  const [faults, setFaults] = useState<FaultKinds>({});
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [st, secs] = await Promise.all([api.state(), api.sections()]);
      setState(st);
      setSections(secs);
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
        onBringUp={act(api.bringup)}
        onBringDown={act(api.bringdown)}
        onReset={act(api.reset)}
      />
      <KpiStrip state={state} />
      <main className="plant" data-testid="plant">
        {sections.map((s) => (
          <SectionCard key={s.id} section={s} status={state.signals.sections[s.id]?.status ?? "offline"} />
        ))}
      </main>
      <SidePanel
        incidents={state.incidents}
        faults={faults}
        sections={sections}
        onInject={(k, t) => act(() => api.inject(k, t))()}
        onResolve={(seq) => act(() => api.resolve(seq))()}
      />
      {error && <div className="err-banner" data-testid="error">{error}</div>}
    </div>
  );
}
