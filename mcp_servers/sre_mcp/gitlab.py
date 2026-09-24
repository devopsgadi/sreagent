"""GitLab MCP server: deployments, MR diffs, pipelines, compare; gated rollback MR action."""
from __future__ import annotations

import datetime as dt
import os
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from . import mocks
from .common import MOCK, clean, http_client, iso, resolve_service, run, utcnow

mcp = FastMCP("gitlab", stateless_http=True)


def _client():
    return http_client(f"{os.environ['GITLAB_URL'].rstrip('/')}/api/v4",
                       {"PRIVATE-TOKEN": os.environ["GITLAB_TOKEN"]})


def _pid(svc: dict) -> str:
    return quote(str(svc["gitlab_project"]), safe="")


@mcp.tool()
def list_deployments(service: str, hours: int = 24) -> list[dict]:
    """Deployments to the service's production environment in the last `hours`, newest first,
    with the merge requests included in each deploy. Key tool for 'what changed?'."""
    svc = resolve_service(service)
    if MOCK:
        return clean(mocks.deployments(svc["name"]))
    since = iso(utcnow() - dt.timedelta(hours=hours))
    out = []
    with _client() as c:
        r = c.get(f"/projects/{_pid(svc)}/deployments", params={
            "environment": svc.get("gitlab_environment", "production"), "updated_after": since,
            "order_by": "updated_at", "sort": "desc", "per_page": 10})
        r.raise_for_status()
        for d in r.json()[:5]:
            sha = d.get("sha")
            mrs = []
            if sha:
                m = c.get(f"/projects/{_pid(svc)}/repository/commits/{sha}/merge_requests")
                if m.status_code == 200:
                    mrs = [{"iid": x["iid"], "title": x["title"]} for x in m.json()]
            out.append({"id": d["id"], "ref": d.get("ref"), "sha": (sha or "")[:10], "status": d.get("status"),
                        "environment": d.get("environment", {}).get("name"), "created_at": d.get("created_at"),
                        "user": (d.get("user") or {}).get("username"), "merge_requests": mrs})
    return clean(out)


@mcp.tool()
def get_merge_request_changes(service: str, mr_iid: int) -> dict:
    """Title, author, merge time and file diffs (truncated) for a merge request. Use after
    list_deployments to inspect what a suspicious deploy changed."""
    svc = resolve_service(service)
    if MOCK:
        return clean(mocks.mr_changes(svc["name"], int(mr_iid)) or {"error": f"MR !{mr_iid} not found"})
    with _client() as c:
        r = c.get(f"/projects/{_pid(svc)}/merge_requests/{mr_iid}")
        r.raise_for_status()
        mr = r.json()
        d = c.get(f"/projects/{_pid(svc)}/merge_requests/{mr_iid}/diffs", params={"per_page": 30})
        files = d.json() if d.status_code == 200 else c.get(
            f"/projects/{_pid(svc)}/merge_requests/{mr_iid}/changes").json().get("changes", [])
    return clean({"iid": mr["iid"], "title": mr["title"], "author": mr["author"]["username"],
                  "merged_at": mr.get("merged_at"), "web_url": mr["web_url"],
                  "merge_commit_sha": mr.get("merge_commit_sha") or mr.get("squash_commit_sha"),
                  "files": [{"path": f.get("new_path"), "diff": f.get("diff", "")} for f in files]}, max_str=1500)


@mcp.tool()
def list_failed_pipelines(service: str, hours: int = 24) -> list[dict]:
    """Failed pipelines on the project in the last `hours`."""
    svc = resolve_service(service)
    if MOCK:
        return mocks.failed_pipelines(svc["name"])
    since = iso(utcnow() - dt.timedelta(hours=hours))
    with _client() as c:
        r = c.get(f"/projects/{_pid(svc)}/pipelines", params={"status": "failed", "updated_after": since, "per_page": 10})
        r.raise_for_status()
    return clean([{"id": p["id"], "ref": p["ref"], "sha": p["sha"][:10], "created_at": p["created_at"],
                   "web_url": p["web_url"]} for p in r.json()])


@mcp.tool()
def compare_refs(service: str, from_ref: str, to_ref: str) -> dict:
    """Commits and changed files between two refs/tags, e.g. from_ref='v2.17.3' to_ref='v2.18.0'."""
    svc = resolve_service(service)
    if MOCK:
        return {"commits": [{"id": "9f3c2ab", "title": "Tune DB pool for new ledger client"}],
                "files": ["helm/values-prod.yaml", "src/main/resources/application.yml"]}
    with _client() as c:
        r = c.get(f"/projects/{_pid(svc)}/repository/compare", params={"from": from_ref, "to": to_ref})
        r.raise_for_status()
        data = r.json()
    return clean({"commits": [{"id": x["short_id"], "title": x["title"], "author": x["author_name"]} for x in data["commits"]],
                  "files": [d["new_path"] for d in data["diffs"]]})


@mcp.tool()
def action_create_rollback_mr(service: str, mr_iid: int, reason: str) -> dict:
    """WRITE ACTION. Create a Draft MR that reverts the given merge request. Never merges.
    Only call when a human approved it."""
    svc = resolve_service(service)
    if MOCK:
        return {"ok": True, "mock": True, "draft_mr_url": f"https://gitlab.internal/{svc['gitlab_project']}/-/merge_requests/4413"}
    pid = _pid(svc)
    stamp = utcnow().strftime("%Y%m%d%H%M%S")
    with _client() as c:
        proj = c.get(f"/projects/{pid}").json()
        default = proj["default_branch"]
        mr = c.get(f"/projects/{pid}/merge_requests/{mr_iid}").json()
        sha = mr.get("merge_commit_sha") or mr.get("squash_commit_sha") or mr.get("sha")
        branch = f"rollback/mr-{mr_iid}-{stamp}"
        c.post(f"/projects/{pid}/repository/branches", params={"branch": branch, "ref": default}).raise_for_status()
        rv = c.post(f"/projects/{pid}/repository/commits/{sha}/revert", json={"branch": branch})
        if rv.status_code >= 400:
            return {"ok": False, "error": f"Revert failed ({rv.status_code}): {rv.text[:300]}", "branch": branch}
        new = c.post(f"/projects/{pid}/merge_requests", json={
            "source_branch": branch, "target_branch": default,
            "title": f"Draft: Revert !{mr_iid} {mr['title']}",
            "description": f"Rollback drafted by SRE agent.\n\nReason: {reason}\n\nReverts !{mr_iid}.",
            "remove_source_branch": True})
        new.raise_for_status()
    return {"ok": True, "draft_mr_url": new.json()["web_url"]}


if __name__ == "__main__":
    run(mcp, 8104)
