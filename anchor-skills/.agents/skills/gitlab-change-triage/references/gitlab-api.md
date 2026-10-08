# GitLab API reference (read-only)

Base: `$GITLAB/api/v4`. Header: `PRIVATE-TOKEN` (a read_api scoped token is sufficient). URL-encode project paths (`group%2Fproject`) or use numeric ids. Paginate with `per_page=100&page=N`. All times ISO-8601 UTC.

## 1. Locate repos
| Purpose | Endpoint | glab |
|---|---|---|
| Find project by name | `GET /projects?search=APP&simple=true` | `glab repo search -s APP` |
| Blob search in group | `GET /groups/:gid/search?scope=blobs&search=APP` | `glab api "groups/:gid/search?scope=blobs&search=APP"` |
| Narrow blob search | `search=namespace: NS filename:values*.yaml` | |
| Project CI file | `GET /projects/:id/repository/files/.gitlab-ci.yml/raw?ref=main` | |

Blob search needs advanced search (Elasticsearch) for group scope on large instances. Otherwise search per project.

## 2. Deployments / environments
| Purpose | Endpoint |
|---|---|
| Environments | `GET /projects/:id/environments` |
| Deployments in window | `GET /projects/:id/deployments?environment=ENV&updated_after=FROM&updated_before=TO&order_by=updated_at&sort=desc` |
| Deployment detail (sha, deployable job) | `GET /projects/:id/deployments/:deployment_id` |

## 3. Pipelines / jobs
| Purpose | Endpoint | glab |
|---|---|---|
| Pipelines in window | `GET /projects/:id/pipelines?updated_after=FROM&updated_before=TO&ref=BRANCH` | `glab ci list` |
| Failed jobs | `GET /projects/:id/pipelines/:pid/jobs?scope[]=failed` | `glab ci view <pid>` |
| Job log (tail it) | `GET /projects/:id/jobs/:job_id/trace` | `glab ci trace <job_id>` |
| Downstream/child pipelines | `GET /projects/:id/pipelines/:pid/bridges` | |

## 4. Changes
| Purpose | Endpoint |
|---|---|
| Compare two refs | `GET /projects/:id/repository/compare?from=GOOD&to=BAD` |
| Commits in window (by path) | `GET /projects/:id/repository/commits?since=FROM&until=TO&path=charts/APP` |
| Commit → MRs | `GET /projects/:id/repository/commits/:sha/merge_requests` |
| Merged MRs in window | `GET /projects/:id/merge_requests?state=merged&updated_after=FROM&updated_before=TO` |
| MR diff | `GET /projects/:id/merge_requests/:iid/diffs` |
| MR approvals | `GET /projects/:id/merge_requests/:iid/approvals` |
| Tags | `GET /projects/:id/repository/tags?search=TAG` |

## 5. Image tag → commit
- Tag contains a short SHA: `GET /projects/:id/repository/commits/SHORT_SHA`
- Tag = pipeline id: `GET /projects/:id/pipelines/:id` → `sha`
- Otherwise: read the build job trace and look for `docker push`, `crane push`, or the `IMAGE_TAG=` line.
- Container registry: `GET /projects/:id/registry/repositories?tags=true` (`created_at` per tag)

## 6. Variables (names only)
- `GET /projects/:id/variables` returns values. **Strip `value` before storing or logging. Never output it.**
- Prefer the audit events (`GET /projects/:id/audit_events`, Premium) for *who changed what, when*.

## Safety
Do not call any POST/PUT/DELETE endpoint, including `pipelines/:id/retry`, `jobs/:id/play`, `merge_requests/:iid/merge`, or `variables`.
