import { useState } from "react";
import { api, SOURCES } from "../api.js";
import ConfirmDialog from "./ConfirmDialog.jsx";

const label = Object.fromEntries(SOURCES.map((s) => [s.key, s.label]));

const ACTIONS = {
  post_work_note: {
    button: "Post RCA to ServiceNow",
    title: "Post this RCA as a work note?",
    body: (inc) => `The summary, evidence and recommendations are added to ${inc} as a work note. Everyone on the incident will see it.`,
    confirm: "Post work note",
    done: (r) => "Work note posted",
  },
  draft_rollback_mr: {
    button: "Draft rollback MR",
    title: "Create a draft rollback MR?",
    body: () => "GitLab gets a new branch that reverts the suspect merge request, plus a Draft MR. Nothing is merged or deployed.",
    confirm: "Create draft MR",
    done: (r) => (r.draft_mr_url ? `Draft MR created: ${r.draft_mr_url}` : "Draft MR created"),
  },
};

export default function RcaPanel({ rca, runId, incident, status, error, actionsEnabled }) {
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState({});

  if (status === "failed") {
    return (
      <section className="rca is-failed" aria-label="RCA draft">
        <h3 className="block-title">RCA draft</h3>
        <p>Triage stopped before an RCA was written.</p>
        <p className="mono small">{error}</p>
        <p className="muted">Check that the MCP servers and LLM endpoint are reachable, then run triage again.</p>
      </section>
    );
  }
  if (!rca) {
    return (
      <section className="rca is-empty" aria-label="RCA draft">
        <h3 className="block-title">RCA draft</h3>
        <p className="muted">
          {status === "running" ? "Written once every source has reported back." : "No RCA for this incident yet."}
        </p>
      </section>
    );
  }

  const hasRollback = (rca.recommended_actions || []).some((a) => a.type === "rollback" && a.mr_iid);

  async function run(action) {
    setBusy(true);
    try {
      const r = await api.action(runId, action);
      setResult((x) => ({ ...x, [action]: { ok: true, text: ACTIONS[action].done(r) } }));
    } catch (e) {
      setResult((x) => ({ ...x, [action]: { ok: false, text: e.message } }));
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  return (
    <section className="rca" aria-label="RCA draft">
      <div className="rca-head">
        <h3 className="block-title">RCA draft</h3>
        <span className={`conf conf-${rca.confidence}`}>{rca.confidence} confidence</span>
      </div>
      <p className="rca-summary">{rca.summary}</p>
      <h4>Probable cause</h4>
      <p>{rca.probable_cause}</p>

      {rca.evidence?.length > 0 && (
        <>
          <h4>Evidence</h4>
          <ul className="evidence">
            {rca.evidence.map((e, i) => (
              <li key={i}>
                <span className={`ev-src src-${e.source}`}>{label[e.source] || e.source}</span>
                <span>{e.finding}</span>
                {e.ref?.startsWith("http") && <a href={e.ref} target="_blank" rel="noreferrer">Open</a>}
              </li>
            ))}
          </ul>
        </>
      )}

      {rca.recommended_actions?.length > 0 && (
        <>
          <h4>Recommended next steps</h4>
          <ol className="recs">
            {rca.recommended_actions.map((a, i) => (
              <li key={i}><strong>{a.action}</strong>{a.details && <span> {a.details}</span>}</li>
            ))}
          </ol>
        </>
      )}

      {rca.open_questions?.length > 0 && (
        <>
          <h4>Open questions</h4>
          <ul className="questions">{rca.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </>
      )}

      <div className="rca-actions">
        <button className="btn primary" onClick={() => setPending("post_work_note")} disabled={busy}>
          {ACTIONS.post_work_note.button}
        </button>
        {hasRollback && (
          <button className="btn" onClick={() => setPending("draft_rollback_mr")} disabled={busy}>
            {ACTIONS.draft_rollback_mr.button}
          </button>
        )}
      </div>
      {!actionsEnabled && (
        <p className="muted small">Write actions are off on this server. An admin can turn them on with ENABLE_ACTIONS=true.</p>
      )}
      {Object.entries(result).map(([k, r]) => (
        <p key={k} className={`small ${r.ok ? "ok-text" : "err-text"}`} role="status">{r.text}</p>
      ))}

      {pending && (
        <ConfirmDialog
          title={ACTIONS[pending].title}
          body={ACTIONS[pending].body(incident)}
          confirmLabel={ACTIONS[pending].confirm}
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={() => run(pending)}
        />
      )}
    </section>
  );
}
