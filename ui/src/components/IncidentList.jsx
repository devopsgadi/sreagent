import { ago } from "../api.js";

function statusOf(inc, activeRunIncident, activeStatus) {
  if (inc.number === activeRunIncident && activeStatus === "running") return { cls: "running", text: "Triaging" };
  const r = inc.last_run;
  if (!r) return { cls: "idle", text: "Not triaged" };
  if (r.status === "running") return { cls: "running", text: "Triaging" };
  if (r.status === "failed") return { cls: "error", text: "Triage failed" };
  return { cls: "done", text: `Triaged${r.confidence ? `, ${r.confidence} confidence` : ""}` };
}

export default function IncidentList({ incidents, error, selected, onSelect, activeRunIncident, activeStatus }) {
  return (
    <nav className="rail" aria-label="Open incidents">
      <h2 className="rail-title">Open incidents</h2>
      {error && <p className="rail-error">ServiceNow didn't respond: {error}</p>}
      {!error && incidents.length === 0 && <p className="rail-empty">No open incidents at P1 to P4.</p>}
      <ul>
        {incidents.map((inc) => {
          const st = statusOf(inc, activeRunIncident, activeStatus);
          const prio = (inc.priority || "").charAt(0);
          return (
            <li key={inc.number}>
              <button
                className={`inc ${selected === inc.number ? "is-selected" : ""}`}
                onClick={() => onSelect(inc)}
                aria-current={selected === inc.number}
              >
                <span className={`prio p${prio}`}>P{prio}</span>
                <span className="inc-body">
                  <span className="inc-num">{inc.number}</span>
                  <span className="inc-desc">{inc.short_description}</span>
                  <span className="inc-meta">
                    <span className={`dot ${st.cls}`} aria-hidden="true" />
                    {st.text}
                    <span className="sep">{ago(inc.opened_at)}</span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
