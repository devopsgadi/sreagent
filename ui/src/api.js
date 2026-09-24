async function req(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) throw new Error((data && data.detail) || `Request failed (${r.status})`);
  return data;
}

export const api = {
  health: () => req("/health"),
  sources: () => req("/sources"),
  incidents: () => req("/incidents"),
  runs: (incident) => req(`/runs?incident=${encodeURIComponent(incident)}`),
  triage: (incident) => req("/triage", { method: "POST", body: JSON.stringify({ incident }) }),
  action: (runId, action) =>
    req(`/runs/${runId}/actions`, { method: "POST", body: JSON.stringify({ action, confirm: true }) }),
  eventsUrl: (runId) => `/api/runs/${runId}/events`,
};

export const SOURCES = [
  { key: "servicenow", label: "ServiceNow", role: "Incident and changes" },
  { key: "datadog", label: "Datadog", role: "Monitors and metrics" },
  { key: "kibana", label: "Kibana", role: "Error logs" },
  { key: "gitlab", label: "GitLab", role: "Deploys and MRs" },
];

export function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
