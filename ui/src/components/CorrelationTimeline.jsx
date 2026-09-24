import { SOURCES, fmtTime } from "../api.js";

export default function CorrelationTimeline({ items, running }) {
  if (!items || items.length === 0) {
    return (
      <section className="timeline is-empty" aria-label="Correlated timeline">
        <h3 className="block-title">Correlated timeline</h3>
        <p className="muted">
          {running ? "Lining up events from each source…" : "Run triage to see what happened, in order, across every source."}
        </p>
      </section>
    );
  }
  const sorted = [...items].sort((a, b) => new Date(a.time) - new Date(b.time));
  const t0 = new Date(sorted[0].time).getTime();
  const t1 = new Date(sorted[sorted.length - 1].time).getTime();
  const span = Math.max(t1 - t0, 60_000);
  const pad = span * 0.08;
  const pos = (iso) => ((new Date(iso).getTime() - t0 + pad) / (span + pad * 2)) * 100;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => new Date(t0 - pad + f * (span + pad * 2)).toISOString());

  return (
    <section className="timeline" aria-label="Correlated timeline">
      <h3 className="block-title">Correlated timeline</h3>
      <div className="tl-grid">
        {SOURCES.map((s) => (
          <div className="tl-row" key={s.key}>
            <span className="tl-label">{s.label}</span>
            <div className="tl-track">
              {sorted.map((it, i) =>
                it.source === s.key ? (
                  <span
                    key={i}
                    className={`tl-mark src-${s.key}`}
                    style={{ left: `${pos(it.time)}%` }}
                    title={`${fmtTime(it.time)} ${it.event}`}
                  >
                    {i + 1}
                  </span>
                ) : null
              )}
            </div>
          </div>
        ))}
        <div className="tl-row tl-axis" aria-hidden="true">
          <span className="tl-label" />
          <div className="tl-track">
            {ticks.map((t, i) => (
              <span key={i} className="tl-tick" style={{ left: `${i * 25}%` }}>{fmtTime(t)}</span>
            ))}
          </div>
        </div>
      </div>
      <ol className="tl-list">
        {sorted.map((it, i) => (
          <li key={i}>
            <span className={`tl-num src-${it.source}`}>{i + 1}</span>
            <time>{fmtTime(it.time)}</time>
            <span>{it.event}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
