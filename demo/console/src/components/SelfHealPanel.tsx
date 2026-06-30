import type { AgentStatus } from "../types";

interface Props {
  agent: AgentStatus | null;
  onStart: () => void;
  onStop: () => void;
  onMode: (m: string) => void;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}

export function SelfHealPanel({ agent, onStart, onStop, onMode, onApprove, onReject }: Props) {
  if (!agent) return null;
  const recent = agent.events.slice().reverse().slice(0, 6);
  return (
    <div className="panel" data-testid="selfheal">
      <div className="panel-head">
        Self-heal
        <button
          className={agent.running ? "sh-toggle on" : "sh-toggle off"}
          data-testid="sh-toggle"
          onClick={agent.running ? onStop : onStart}
        >
          {agent.running ? "● ON" : "○ OFF"}
        </button>
      </div>
      <div className="sh-body">
        <div className="sh-modes">
          {["auto", "approve"].map((m) => (
            <button
              key={m}
              className={agent.mode === m ? "sh-mode active" : "sh-mode"}
              data-testid={`sh-mode-${m}`}
              onClick={() => onMode(m)}
            >
              {m}
            </button>
          ))}
          <span className={`sh-state st-${agent.state}`}>{agent.state}</span>
        </div>
        <ul className="sh-events" data-testid="sh-events">
          {recent.length === 0 && <li className="empty">No actions yet</li>}
          {recent.map((e) => (
            <li
              key={e.id}
              className={`sh-ev ${e.approved === true ? "done" : e.approved === false ? "rej" : "pend"}`}
              data-testid={`sh-ev-${e.id}`}
            >
              <div className="sh-ev-act">{e.action}</div>
              <div className="sh-ev-foot">
                <span className="sh-ev-tgt">
                  {e.kind} · {e.target}
                </span>
                {e.approved === null && e.auto && (
                  <span className="sh-auto">auto-heal in {e.countdown}</span>
                )}
                {e.approved === null && !e.auto && (
                  <span className="sh-btns">
                    <button onClick={() => onApprove(e.id)}>Approve</button>
                    <button className="ghost" onClick={() => onReject(e.id)}>
                      Reject
                    </button>
                  </span>
                )}
                {e.approved === true && <span className="sh-ok">✓ healed</span>}
                {e.approved === false && <span className="sh-no">rejected</span>}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
