import { useCallback, useEffect, useState } from "react";
import { api, SOURCES, ago } from "./api.js";
import { useTriageStream } from "./hooks/useTriageStream.js";
import IncidentList from "./components/IncidentList.jsx";
import SourceLanes from "./components/SourceLanes.jsx";
import CorrelationTimeline from "./components/CorrelationTimeline.jsx";
import ActivityFeed from "./components/ActivityFeed.jsx";
import RcaPanel from "./components/RcaPanel.jsx";

function Elapsed({ start, end }) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    if (end) return undefined;
    const t = setInterval(() => setNow(Date.now() / 1000), 500);
    return () => clearInterval(t);
  }, [end]);
  if (!start) return null;
  const s = Math.max(0, Math.round((end || now) - start));
  return <span>{s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`}</span>;
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [srcHealth, setSrcHealth] = useState({});
  const [incidents, setIncidents] = useState([]);
  const [incError, setIncError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [runId, setRunId] = useState(null);
  const [startError, setStartError] = useState(null);
  const stream = useTriageStream(runId);

  const loadIncidents = useCallback(async () => {
    try {
      const r = await api.incidents();
      setIncidents(r.incidents || []);
      setIncError(r.error);
    } catch (e) {
      setIncError(e.message);
    }
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.sources().then(setSrcHealth).catch(() => setSrcHealth({}));
    loadIncidents();
    const t = setInterval(loadIncidents, 30_000);
    return () => clearInterval(t);
  }, [loadIncidents]);

  useEffect(() => {
    if (stream.status === "triaged" || stream.status === "failed") loadIncidents();
  }, [stream.status, loadIncidents]);

  function select(inc) {
    setSelected(inc.number);
    setStartError(null);
    setRunId(inc.last_run ? inc.last_run.id : null);
  }

  async function startTriage() {
    if (!selected) return;
    setStartError(null);
    try {
      const r = await api.triage(selected);
      setRunId(r.run_id);
    } catch (e) {
      setStartError(e.message);
    }
  }

  const inc = incidents.find((i) => i.number === selected);
  const running = stream.status === "running";
  const doneSources = Object.values(stream.sources).filter((s) => ["done", "error", "skipped", "offline"].includes(s.state)).length;
  const progress = stream.status === "triaged" ? 100 : running ? Math.min(95, 8 + doneSources * 20 + (stream.rca ? 10 : 0)) : 0;

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">SRE agent</span>
        <ul className="health" aria-label="Source health">
          {SOURCES.map((s) => {
            const h = srcHealth[s.key];
            return (
              <li key={s.key} title={h?.error || (h ? `${h.tools.length} tools` : "Unknown")}>
                <span className={`dot ${h ? (h.ok ? "done" : "error") : "idle"}`} aria-hidden="true" />
                {s.label}
              </li>
            );
          })}
        </ul>
        {health && <span className="mode">{health.llm === "mock" ? "Demo mode" : `LLM: ${health.llm}`}</span>}
      </header>

      <IncidentList
        incidents={incidents}
        error={incError}
        selected={selected}
        onSelect={select}
        activeRunIncident={selected}
        activeStatus={stream.status}
      />

      <main className="main">
        {!inc ? (
          <div className="empty-main">
            <h1>Pick an incident to triage</h1>
            <p>
              The agent pulls the ticket from ServiceNow, checks Datadog and Kibana for impact and errors,
              lines them up against GitLab deploys, and drafts an RCA you can post back to the ticket.
            </p>
          </div>
        ) : (
          <>
            <div className="inc-header">
              <div>
                <p className="inc-kicker"><span className="mono">{inc.number}</span><span>{inc.service || inc.cmdb_ci}</span><span>Opened {ago(inc.opened_at)}</span></p>
                <h1>{inc.short_description}</h1>
              </div>
              <div className="inc-cta">
                <button className="btn primary" onClick={startTriage} disabled={running}>
                  {running ? "Triaging…" : stream.status === "idle" ? "Run triage" : "Run again"}
                </button>
                <span className="elapsed">
                  {running && <>Running <Elapsed start={stream.startedAt} /></>}
                  {stream.status === "triaged" && <>Triaged in <Elapsed start={stream.startedAt} end={stream.finishedAt} /></>}
                </span>
              </div>
            </div>
            {startError && <p className="err-text">{startError}</p>}
            <div className={`progress ${running ? "is-running" : ""}`} role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${progress}%` }} />
            </div>

            <SourceLanes sources={stream.sources} />
            <CorrelationTimeline items={stream.rca?.timeline} running={running} />

            <div className="split">
              <ActivityFeed activity={stream.activity} notes={stream.notes} step={stream.step} status={stream.status} />
              <RcaPanel
                rca={stream.rca}
                runId={runId}
                incident={inc.number}
                status={stream.status}
                error={stream.error}
                actionsEnabled={health?.actions_enabled}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
