import { useState } from "react";

import { api } from "../api";
import type { AgentStatus, Incident } from "../types";

const VULCAN_STEPS = [
  "Read plant state",
  "Enumerate open incidents",
  "Trace cascade → root cause",
  "Match failure mode → remediation",
  "Prove & propose action",
];

const STATE_LABEL: Record<string, string> = {
  idle: "Idle",
  monitoring: "Monitoring",
  remediating: "Remediating",
};

interface Props {
  agent: AgentStatus;
  onRefresh: () => void;
  active?: Incident;
  phase: number;
  vStep: number;
  rootId?: string;
  safe: boolean;
  remediation: string;
  onApprove: () => void;
  onReject: () => void;
}

export function AgentPanel({
  agent, onRefresh, active, phase, vStep, rootId, safe, remediation, onApprove, onReject,
}: Props) {
  // defensive default in case the backend status predates the config fields
  const cfg = agent.config ?? {
    provider: "vulcan", model: "vulcan-0.1", base_url: "", has_key: false, providers: {},
  };
  const providers = cfg.providers ?? {};
  const [provider, setProvider] = useState(cfg.provider);
  const [model, setModel] = useState(cfg.model);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(cfg.base_url);
  const [prompt, setPrompt] = useState(agent.system_prompt);
  const [promptDirty, setPromptDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  const models = providers[provider]?.models ?? [];
  const isLocal = providers[provider]?.local ?? false;
  const phaseKey = ["inject", "cascade", "collapse", "investigate", "propose", "resolution"][phase];

  const onProvider = (p: string) => {
    setProvider(p);
    const m = providers[p]?.models?.[0]?.id;
    if (m) setModel(m);
    setSaved(false);
  };
  const saveConfig = async () => {
    await api.agentSetConfig(provider, model, apiKey || undefined, baseUrl || undefined);
    setApiKey("");
    setSaved(true);
    onRefresh();
  };
  const savePrompt = async () => {
    await api.agentSetPrompt(prompt);
    setPromptDirty(false);
    onRefresh();
  };
  const polish = async () => {
    const r = await api.agentPolishPrompt();
    setPrompt(r.prompt);
    setPromptDirty(false);
    onRefresh();
  };

  return (
    <aside className="inv-agent" data-testid="inv-agent">
      <div className="agent-head">
        <span className="agent-title">🔒 VULCAN AGENT</span>
        <span className={`agent-state st-${phaseKey}`}>{STATE_LABEL[agent.state] ?? agent.state}</span>
      </div>

      <div className="agent-section">
        <div className="agent-row">
          <span>provider</span>
          <select value={provider} onChange={(e) => onProvider(e.target.value)} data-testid="inv-model">
            {Object.entries(providers).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>
        <div className="agent-row">
          <span>model</span>
          <select value={model} onChange={(e) => { setModel(e.target.value); setSaved(false); }}>
            {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
        {!isLocal && (
          <>
            <div className="agent-row">
              <span>API key</span>
              <input type="password" value={apiKey} data-testid="agent-key"
                onChange={(e) => { setApiKey(e.target.value); setSaved(false); }}
                placeholder={cfg.has_key ? "•••• configured" : "enter key"} />
            </div>
            <div className="agent-row">
              <span>base URL</span>
              <input value={baseUrl} placeholder="https://…/v1 (send elsewhere)"
                onChange={(e) => { setBaseUrl(e.target.value); setSaved(false); }} />
            </div>
          </>
        )}
        <button className="agent-save" data-testid="agent-save" onClick={saveConfig}>
          {saved ? "✓ Saved" : "Save model"}
        </button>
        <div className="agent-det">
          {isLocal ? "local · deterministic — same 5 steps, every run" : "cloud · non-deterministic"}
        </div>
      </div>

      <div className="agent-section">
        <div className="agent-steps-label">system prompt</div>
        <textarea className="agent-prompt" rows={4} value={prompt} data-testid="agent-prompt"
          onChange={(e) => { setPrompt(e.target.value); setPromptDirty(true); }} />
        <div className="prop-btns">
          <button onClick={polish} data-testid="agent-polish">Polish</button>
          <button onClick={savePrompt} disabled={!promptDirty}>Save prompt</button>
        </div>
      </div>

      <div className="agent-actions">
        <button className={agent.running ? "sh-toggle on" : "sh-toggle off"} data-testid="agent-power"
          onClick={() => (agent.running ? api.agentStop() : api.agentStart()).then(onRefresh)}>
          {agent.running ? "● ON" : "○ OFF"}
        </button>
        {["auto", "approve"].map((m) => (
          <button key={m} className={agent.mode === m ? "sh-mode active" : "sh-mode"} data-testid={`agent-mode-${m}`}
            onClick={() => api.agentMode(m).then(onRefresh)}>{m}</button>
        ))}
      </div>

      <div className="agent-steps-label">investigation</div>
      <ol className="vulcan-steps" data-testid="vulcan">
        {VULCAN_STEPS.map((s, i) => {
          const done = !!active && (phase > 3 || (phaseKey === "investigate" && i < vStep));
          const cur = !!active && phaseKey === "investigate" && i === vStep;
          return (
            <li key={i} className={done ? "done" : cur ? "active" : ""}>
              <b>{done ? "✓" : cur ? "▸" : "·"}</b> {s}
              {i === 2 && done && <em> → {rootId}</em>}
            </li>
          );
        })}
      </ol>

      {active && phaseKey === "propose" && (
        <div className="agent-proposal" data-testid="agent-proposal">
          <div className="prop-action">{remediation}</div>
          <div className="prop-tag">
            {active.kind} · {active.target} · conf {safe ? 5 : 3}/5
          </div>
          <div className="prop-btns">
            <button className="inv-approve" data-testid="inv-approve" onClick={onApprove}>✓ Approve</button>
            <button className="inv-reject" data-testid="inv-reject" onClick={onReject}>✕ Reject</button>
          </div>
        </div>
      )}

      {agent.events.length > 0 && (
        <div className="agent-log" data-testid="agent-log">
          <div className="agent-steps-label">activity</div>
          {[...agent.events].reverse().slice(0, 8).map((e) => (
            <div key={e.id} className={`log-row ${e.approved === true ? "done" : e.approved === false ? "rej" : "pend"}`}>
              <b>{e.approved === true ? "✓ healed" : e.approved === false ? "rejected" : e.auto ? "auto" : "proposed"}</b>{" "}
              {e.kind} · {e.target}
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
