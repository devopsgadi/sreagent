import { SOURCES } from "../api.js";

const LABEL = {
  idle: "Queued", waiting: "Connected", running: "Querying", done: "Reported",
  error: "Failed", offline: "Unreachable", skipped: "Not needed",
};

export default function SourceLanes({ sources }) {
  return (
    <section className="lanes" aria-label="Sources">
      {SOURCES.map((s) => {
        const st = sources[s.key] || { state: "idle", calls: 0 };
        return (
          <div key={s.key} className={`lane src-${s.key} is-${st.state}`}>
            <div className="lane-top">
              <span className="lane-name">{s.label}</span>
              <span className="lane-state">{LABEL[st.state] || st.state}</span>
            </div>
            <div className="lane-role">{s.role}</div>
            <div className="lane-calls">
              {st.calls > 0 ? `${st.calls} ${st.calls === 1 ? "query" : "queries"}` : "\u00a0"}
              {st.errors > 0 && <span className="lane-err">, {st.errors} failed</span>}
            </div>
          </div>
        );
      })}
    </section>
  );
}
