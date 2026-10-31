# Playbook — React micro-apps / micro-frontends

Entry: blank page, "UI not loading", chunk load errors reported by users, `FE-*` signatures, 404s on `.js/.css/remoteEntry.js`.

Browser console errors are not in Kibana unless RUM (Elastic APM RUM / Datadog RUM) is indexed. Infer from server-side asset and API logs.

## 1. Shape of a micro-app request
User → Akamai (caching) → F5/NGINX Plus → Istio gateway → micro-app pod (NGINX serving static build, sometimes proxying `/api`) → BFF/API services.
Shell app loads `remoteEntry.js` from each micro-app (Module Federation) or import maps; then hashed chunks `main.<hash>.js`.

## 2. Failure patterns
| Evidence | Meaning |
|---|---|
| 404 on `*.<hash>.js` right after release | Version skew: cached `index.html`/`remoteEntry.js` (Akamai/browser) references chunks removed by new build. Old+new pods during rollout serving different builds (request for old chunk lands on new pod) |
| 404 only on canary subset | Canary build missing asset/path; or shell routes to wrong subset |
| 404 on `remoteEntry.js` for one micro-app | That micro-app's path/route broken (VS prefix, NGINX `location`, base href) |
| 200 for `index.html` but API calls 401/403 | Auth/session (cookie domain, SameSite, token) — go to API traces |
| OPTIONS 4xx/5xx (FE-04) | CORS preflight: gateway/app not allowing origin/headers; AuthorizationPolicy denying OPTIONS |
| 431 / FE-05 | Cookie bloat (many micro-apps setting cookies under same domain) |
| 502/504 for `/api` via NGINX-in-pod (FE-03) | Pod's NGINX proxy to API failing — `upstream timed out`, `no live upstreams`, DNS resolution at NGINX start (static resolve of a Service that changed) |
| `open() ... failed (2: No such file or directory)` (FE-02) | File missing in image; wrong `root`; SPA fallback (`try_files $uri /index.html`) missing → deep links 404 |
| Content-Type `text/html` for `.js` | SPA fallback returning index.html for missing chunk → browser "Unexpected token <" |
| `Content-Security-Policy` violation reports (if report-uri indexed) | New third-party origin not allowed |

## 3. Queries
- Asset errors by path pattern and subset: `SIDECAR and upstream_cluster:inbound* and path:(*.js or *.css or *remoteEntry*) and response_code >= 400` → terms `path`, `{pod}`, `{version}`.
- Pod-to-build mapping: `{image}` per pod; check whether 404 chunks only hit new-image pods.
- Gateway view: same filter on GATEWAY, split by `authority` (multiple hosts → which micro-app).
- Akamai: if logs indexed (DataStream), cache status (`TCP_HIT`/`TCP_MISS`) on `index.html` / `remoteEntry.js`.

## 4. Typical root causes & evidence to cite
- Missing `Cache-Control: no-cache` on `index.html`/`remoteEntry.js` → stale entry points after release.
- Old assets not retained across releases (no asset bucket/CDN versioning) → chunk 404s for long-lived browser tabs.
- Rollout with mixed versions + no session affinity → intermittent chunk 404s for minutes.
- Base path change (`PUBLIC_URL` / `homepage`) not matched by VS `prefix` rewrite.

## 5. Output
Micro-app name, host/path, first 404/5xx time vs rollout time, affected subset, whether stale cache (Akamai/browser) vs missing file vs routing. Escalation asks: Akamai purge status, response headers (`curl -I`).
