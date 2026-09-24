import { useEffect, useReducer } from "react";
import { api, SOURCES } from "../api.js";

const EVENT_TYPES = [
  "run_started", "sources", "llm_step", "agent_note", "tool_started",
  "tool_finished", "rca_ready", "run_finished", "run_failed", "action_done",
];

function initial() {
  const sources = {};
  SOURCES.forEach((s) => (sources[s.key] = { state: "idle", calls: 0, errors: 0, inflight: 0 }));
  return { status: "idle", sources, activity: [], notes: [], rca: null, error: null, step: null, startedAt: null, finishedAt: null };
}

function settle(src) {
  if (src.inflight > 0) return "running";
  if (src.calls > 0 && src.errors === src.calls) return "error";
  return src.calls > 0 ? "done" : src.state;
}

function reducer(state, action) {
  if (action.type === "reset") return initial();
  const ev = action.ev;
  const d = ev.data || {};
  const s = { ...state, sources: { ...state.sources } };
  switch (ev.type) {
    case "run_started":
      return { ...initial(), status: "running", startedAt: ev.ts };
    case "sources":
      Object.keys(s.sources).forEach((k) => {
        s.sources[k] = { ...s.sources[k], state: k in (d.available || {}) ? "waiting" : "offline" };
      });
      return s;
    case "llm_step":
      return { ...s, step: d.step };
    case "agent_note":
      return { ...s, notes: [...s.notes, d.text] };
    case "tool_started": {
      const src = { ...(s.sources[d.source] || { calls: 0, errors: 0, inflight: 0 }) };
      src.inflight += 1;
      src.state = "running";
      s.sources[d.source] = src;
      s.activity = [...s.activity, { ...d, state: "running", startedTs: ev.ts }];
      return s;
    }
    case "tool_finished": {
      const src = { ...(s.sources[d.source] || { calls: 0, errors: 0, inflight: 1 }) };
      src.inflight = Math.max(0, src.inflight - 1);
      src.calls += 1;
      if (!d.ok) src.errors += 1;
      src.state = settle(src);
      s.sources[d.source] = src;
      s.activity = s.activity.map((a) => (a.call_id === d.call_id ? { ...a, ...d, state: d.ok ? "done" : "error" } : a));
      return s;
    }
    case "rca_ready":
      return { ...s, rca: d };
    case "run_finished":
      Object.keys(s.sources).forEach((k) => {
        if (s.sources[k].state === "waiting") s.sources[k] = { ...s.sources[k], state: "skipped" };
      });
      return { ...s, status: "triaged", finishedAt: ev.ts, step: null };
    case "run_failed":
      return { ...s, status: "failed", error: d.error, finishedAt: ev.ts, step: null };
    default:
      return s;
  }
}

export function useTriageStream(runId) {
  const [state, dispatch] = useReducer(reducer, undefined, initial);

  useEffect(() => {
    dispatch({ type: "reset" });
    if (!runId) return undefined;
    const es = new EventSource(api.eventsUrl(runId));
    const onEvent = (e) => dispatch({ ev: JSON.parse(e.data) });
    EVENT_TYPES.forEach((t) => es.addEventListener(t, onEvent));
    const close = () => es.close();
    es.addEventListener("run_finished", close);
    es.addEventListener("run_failed", close);
    return close;
  }, [runId]);

  return state;
}
