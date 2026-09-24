import { useState } from "react";
import { SOURCES } from "../api.js";

const label = Object.fromEntries(SOURCES.map((s) => [s.key, s.label]));

function Args({ args }) {
  const parts = Object.entries(args || {}).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  return <span className="args">({parts.join(", ")})</span>;
}

function Row({ a }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={`act is-${a.state}`}>
      <button className="act-head" onClick={() => setOpen(!open)} aria-expanded={open} disabled={a.state === "running"}>
        <span className={`act-src src-${a.source}`}>{label[a.source] || a.source}</span>
        <code className="act-call">{a.tool}<Args args={a.args} /></code>
        <span className="act-time">
          {a.state === "running" ? "running" : a.state === "error" ? "failed" : `${a.duration_ms} ms`}
        </span>
      </button>
      {a.preview && !open && <p className="act-preview">{a.preview}</p>}
      {open && <pre className="act-result">{pretty(a.result)}</pre>}
    </li>
  );
}

function pretty(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

export default function ActivityFeed({ activity, notes, step, status }) {
  return (
    <section className="feed" aria-label="Agent activity" aria-live="polite">
      <h3 className="block-title">
        Agent activity
        {status === "running" && step && <span className="step">{step === "summarize" ? "Writing RCA" : `Step ${step}`}</span>}
      </h3>
      {activity.length === 0 && (
        <p className="muted">{status === "running" ? "Connecting to sources…" : "Tool calls appear here as the agent investigates."}</p>
      )}
      <ul>
        {activity.map((a) => <Row key={a.call_id} a={a} />)}
      </ul>
      {notes.length > 0 && (
        <div className="notes">
          {notes.map((n, i) => <p key={i}>{n}</p>)}
        </div>
      )}
    </section>
  );
}
