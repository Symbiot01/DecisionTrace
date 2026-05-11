import logging

from layerten.fetch.http_client import get_rest_client
from layerten.fetch.rate_limiter import (
    MAX_RETRIES,
    check_rate_limit,
    handle_rate_limit_error,
    is_rate_limited,
)

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_paginated(
    url: str,
    token: str,
    params: dict | None = None,
    per_page: int = 100,
) -> list[dict]:
    """Fetch all pages from a paginated REST endpoint."""
    results: list[dict] = []
    params = dict(params or {})
    params["per_page"] = per_page
    page = 1
    client = get_rest_client()

    while True:
        params["page"] = page

        for attempt in range(MAX_RETRIES):
            resp = client.get(url, headers=_headers(token), params=params)

            if is_rate_limited(resp):
                handle_rate_limit_error(resp, attempt)
                continue

            resp.raise_for_status()
            check_rate_limit(resp)
            break
        else:
            raise RuntimeError(f"Exhausted retries fetching {url} page {page}")

        data = resp.json()
        if not data:
            break

        results.extend(data)
        logger.debug("Fetched page %d from %s (%d items)", page, url, len(data))

        if len(data) < per_page:
            break
        page += 1

    return results


def fetch_commits_metadata(owner: str, repo: str, token: str) -> list[dict]:
    """Fetch commit metadata from REST API (author login, verified status)."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    raw = fetch_paginated(url, token)
    results = []
    for c in raw:
        results.append({
            "sha": c["sha"],
            "author_login": c["author"]["login"] if c.get("author") else None,
            "committer_login": c["committer"]["login"] if c.get("committer") else None,
            "verified": c.get("commit", {}).get("verification", {}).get("verified", False),
            "message": c.get("commit", {}).get("message", ""),
            "html_url": c.get("html_url", ""),
        })
    return results


def fetch_branches(owner: str, repo: str, token: str) -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/branches"
    raw = fetch_paginated(url, token)
    return [
        {
            "name": b["name"],
            "commit_sha": b["commit"]["sha"],
            "protected": b.get("protected", False),
        }
        for b in raw
    ]


def fetch_labels(owner: str, repo: str, token: str) -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/labels"
    raw = fetch_paginated(url, token)
    return [
        {
            "name": l["name"],
            "color": l.get("color", ""),
            "description": l.get("description", ""),
        }
        for l in raw
    ]


def fetch_releases(owner: str, repo: str, token: str) -> list[dict]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases"
    raw = fetch_paginated(url, token)
    return [
        {
            "tag_name": r["tag_name"],
            "name": r.get("name", ""),
            "body": r.get("body", ""),
            "draft": r.get("draft", False),
            "prerelease": r.get("prerelease", False),
            "created_at": r.get("created_at", ""),
            "published_at": r.get("published_at", ""),
            "author_login": r["author"]["login"] if r.get("author") else None,
            "html_url": r.get("html_url", ""),
        }
        for r in raw
    ]
