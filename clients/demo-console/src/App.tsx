import { useCallback, useEffect, useState } from "react";
import s from "./App.module.css";
import redhatLogo from "./assets/redhat-logo.svg";
import { fetchFleet, fetchPool, isLive, runJob, schedule } from "./api";
import type { AgentRecord, JobResult, PoolCapacity } from "./types";

const GiB = 1024 ** 3;

export default function App() {
  const [fleet, setFleet] = useState<AgentRecord[]>([]);
  const [pool, setPool] = useState<PoolCapacity | null>(null);
  const [prompt, setPrompt] = useState("Summarize Red Hat's open hybrid cloud strategy in one sentence.");
  const [running, setRunning] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);

  const refresh = useCallback(async () => {
    const [f, p] = await Promise.all([fetchFleet(), fetchPool()]);
    setFleet(f);
    setPool(p);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onRun = useCallback(async () => {
    setRunning(true);
    setResult(null);
    setChosen(null);
    try {
      const node = await schedule(true);
      setChosen(node.agentId);
      const r = await runJob(node.agentId, prompt);
      setResult(r);
    } finally {
      setRunning(false);
    }
  }, [prompt]);

  return (
    <div className={s.shell}>
      <header className={s.top}>
        <img src={redhatLogo} alt="Red Hat" className={s.logo} />
        <div>
          <h1 className={s.title}>Bard — Stranded Compute Pool</h1>
          <div className={s.subtitle}>
            Idle CPU / GPU / storage across the fleet, pooled as a secure, schedulable resource ·
            rootless Podman on UBI · SELinux-confined
          </div>
        </div>
        <span className={`${s.badge} ${isLive ? s.live : s.seed}`}>{isLive ? "LIVE" : "DEMO DATA"}</span>
      </header>

      {pool && (
        <section className={s.kpis}>
          <Kpi label="Pooled nodes" value={String(pool.nodes)} />
          <Kpi label="vCPUs reclaimed" value={String(pool.cpus)} />
          <Kpi label="Memory" value={`${Math.round(pool.memoryBytes / GiB)} GiB`} />
          <Kpi label="GPU nodes" value={String(pool.gpuNodes)} accent />
          <div className={s.tagline}>No new hardware — capacity the org already owns and powers.</div>
        </section>
      )}

      <section className={s.runbar}>
        <input className={s.input} value={prompt} onChange={(e) => setPrompt(e.target.value)} disabled={running} />
        <button className={s.run} onClick={() => void onRun()} disabled={running || !prompt.trim()}>
          {running ? "Scheduling…" : "Run inference (GPU-preferred)"}
        </button>
      </section>

      {(chosen || result) && (
        <section className={s.outcome}>
          <span className={s.placed}>
            scheduled → <strong>{chosen}</strong>
          </span>
          {result && <span className={s.answer}>{result.content}</span>}
        </section>
      )}

      <section className={s.fleet}>
        {fleet.map((n) => {
          const pp = n.powerProfile;
          const gpu = pp?.gpus ?? null;
          const active = chosen === n.agentId;
          return (
            <article key={n.agentId} className={`${s.node} ${active ? s.active : ""} ${gpu ? s.gpu : ""}`}>
              <div className={s.nodeHead}>
                <span className={s.nodeName}>{n.agentId}</span>
                <span className={`${s.dot} ${active ? (result ? s.done : s.busy) : s.idle}`} />
              </div>
              <div className={s.caps}>
                {(n.capabilities ?? []).map((c) => (
                  <span key={c} className={s.cap}>
                    {c}
                  </span>
                ))}
              </div>
              <dl className={s.specs}>
                <span>{pp?.cpus ?? "—"} vCPU</span>
                <span>{pp?.memory ?? "—"}</span>
                <span>{gpu ? `GPU: ${gpu}` : "no GPU"}</span>
              </dl>
              <div className={s.confine}>rootless · UBI 9 · Podman</div>
            </article>
          );
        })}
      </section>
    </div>
  );
}

function Kpi({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`${s.kpi} ${accent ? s.kpiAccent : ""}`}>
      <div className={s.kpiVal}>{value}</div>
      <div className={s.kpiLabel}>{label}</div>
    </div>
  );
}
