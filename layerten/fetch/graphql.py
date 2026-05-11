import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from layerten import config
from layerten.fetch.http_client import get_graphql_client
from layerten.fetch.queries import (
    DISCUSSION_COMMENTS_SUBPAGE_QUERY,
    DISCUSSION_QUERY,
    ISSUE_COMMENTS_SUBPAGE_QUERY,
    ISSUE_QUERY,
    PR_COMMENTS_SUBPAGE_QUERY,
    PR_QUERY,
    PR_REVIEWS_SUBPAGE_QUERY,
)
from layerten.fetch.rate_limiter import (
    MAX_RETRIES,
    check_rate_limit,
    handle_rate_limit_error,
    is_rate_limited,
)

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.github.com/graphql"

# Cap concurrent GraphQL HTTP calls across parallel bootstrap + enrich workers
_graphql_sema: threading.Semaphore | None = None
_graphql_sema_lock = threading.Lock()

# on_page(nodes, resume_cursor_or_None) — resume_cursor is endCursor after this page
PageCallback = Callable[[list[dict], str | None], None]


def _get_graphql_sema() -> threading.Semaphore:
    global _graphql_sema
    with _graphql_sema_lock:
        if _graphql_sema is None:
            n = max(1, int(getattr(config, "GITHUB_MAX_CONCURRENCY", 8)))
            _graphql_sema = threading.Semaphore(n)
        return _graphql_sema


def graphql_request(query: str, variables: dict, token: str) -> dict:
    """Execute a single GraphQL request with retry/rate-limit handling."""
    headers = {"Authorization": f"Bearer {token}"}
    client = get_graphql_client()
    sema = _get_graphql_sema()

    for attempt in range(MAX_RETRIES):
        with sema:
            resp = client.post(
                GRAPHQL_URL,
                json={"query": query, "variables": variables},
                headers=headers,
            )

        if is_rate_limited(resp):
            handle_rate_limit_error(resp, attempt)
            continue

        resp.raise_for_status()
        check_rate_limit(resp)

        data = resp.json()
        if "errors" in data:
            errors = data["errors"]
            error_types = [e.get("type", "") for e in errors]
            if "RATE_LIMITED" in error_types:
                handle_rate_limit_error(resp, attempt)
                continue
            raise RuntimeError(f"GraphQL errors: {errors}")

        return data["data"]

    raise RuntimeError("Exhausted retries for GraphQL request")

def _paginate_nested_reviews(
    owner: str, repo: str, pr_number: int, token: str, after_cursor: str
) -> list[dict]:
    """Fetch remaining review pages for a PR that has >50 reviews."""
    all_reviews: list[dict] = []
    cursor = after_cursor
    while cursor:
        data = graphql_request(
            PR_REVIEWS_SUBPAGE_QUERY,
            {"owner": owner, "repo": repo, "prNumber": pr_number, "cursor": cursor},
            token,
        )
        connection = data["repository"]["pullRequest"]["reviews"]
        all_reviews.extend(connection["nodes"])
        if connection["pageInfo"]["hasNextPage"]:
            cursor = connection["pageInfo"]["endCursor"]
        else:
            break
    return all_reviews


def _paginate_nested_comments(
    query: str,
    path_to_connection: list[str],
    owner: str,
    repo: str,
    number: int,
    number_key: str,
    token: str,
    after_cursor: str,
) -> list[dict]:
    """Fetch remaining comment pages for a PR/issue/discussion."""
    all_comments: list[dict] = []
    cursor = after_cursor
    while cursor:
        variables = {"owner": owner, "repo": repo, number_key: number, "cursor": cursor}
        data = graphql_request(query, variables, token)
        obj = data
        for key in path_to_connection:
            obj = obj[key]
        all_comments.extend(obj["nodes"])
        if obj["pageInfo"]["hasNextPage"]:
            cursor = obj["pageInfo"]["endCursor"]
        else:
            break
    return all_comments


def _enrich_pr(pr: dict, owner: str, repo: str, token: str) -> dict:
    """Fetch sub-pages for reviews/comments if the first page was truncated."""
    reviews = pr.get("reviews", {})
    if reviews.get("pageInfo", {}).get("hasNextPage"):
        extra = _paginate_nested_reviews(
            owner, repo, pr["number"], token,
            reviews["pageInfo"]["endCursor"],
        )
        reviews["nodes"].extend(extra)
        logger.debug(
            "PR #%d: fetched %d extra review pages", pr["number"], len(extra)
        )

    comments = pr.get("comments", {})
    if comments.get("pageInfo", {}).get("hasNextPage"):
        extra = _paginate_nested_comments(
            PR_COMMENTS_SUBPAGE_QUERY,
            ["repository", "pullRequest", "comments"],
            owner, repo, pr["number"], "prNumber", token,
            comments["pageInfo"]["endCursor"],
        )
        comments["nodes"].extend(extra)
        logger.debug(
            "PR #%d: fetched %d extra comments", pr["number"], len(extra)
        )

    return pr


def _enrich_issue(issue: dict, owner: str, repo: str, token: str) -> dict:
    """Fetch sub-pages for comments if the first page was truncated."""
    comments = issue.get("comments", {})
    if comments.get("pageInfo", {}).get("hasNextPage"):
        extra = _paginate_nested_comments(
            ISSUE_COMMENTS_SUBPAGE_QUERY,
            ["repository", "issue", "comments"],
            owner, repo, issue["number"], "issueNumber", token,
            comments["pageInfo"]["endCursor"],
        )
        comments["nodes"].extend(extra)
        logger.debug(
            "Issue #%d: fetched %d extra comments", issue["number"], len(extra)
        )
    return issue


def _enrich_discussion(disc: dict, owner: str, repo: str, token: str) -> dict:
    """Fetch sub-pages for comments if the first page was truncated."""
    comments = disc.get("comments", {})
    if comments.get("pageInfo", {}).get("hasNextPage"):
        extra = _paginate_nested_comments(
            DISCUSSION_COMMENTS_SUBPAGE_QUERY,
            ["repository", "discussion", "comments"],
            owner, repo, disc["number"], "discNumber", token,
            comments["pageInfo"]["endCursor"],
        )
        comments["nodes"].extend(extra)
        logger.debug(
            "Discussion #%d: fetched %d extra comments", disc["number"], len(extra)
        )
    return disc


def _enrich_page_parallel(
    nodes: list[dict],
    enrich_fn,
    owner: str,
    repo: str,
    token: str,
) -> list[dict]:
    """Enrich page nodes in parallel while preserving order."""
    if not nodes:
        return []
    workers = min(
        len(nodes),
        max(1, int(getattr(config, "GITHUB_MAX_CONCURRENCY", 8))),
    )
    if workers == 1 or len(nodes) == 1:
        return [enrich_fn(n, owner, repo, token) for n in nodes]

    enriched: list[dict | None] = [None] * len(nodes)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(enrich_fn, node, owner, repo, token): idx
            for idx, node in enumerate(nodes)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            enriched[idx] = fut.result()
    return [n for n in enriched if n is not None]


def fetch_all_prs(
    owner: str,
    repo: str,
    token: str,
    start_cursor: str | None = None,
    on_page: PageCallback | None = None,
) -> tuple[list[dict], str | None]:
    """
    Fetch all PRs with nested reviews, comments, and timeline.
    Returns (prs_list, last_cursor_or_None).
    Outer pages stay sequential; nested enrichment is parallel per page.
    """
    all_prs: list[dict] = []
    cursor = start_cursor
    page_num = 0

    while True:
        page_num += 1
        variables = {"owner": owner, "repo": repo, "cursor": cursor}
        data = graphql_request(PR_QUERY, variables, token)

        connection = data["repository"]["pullRequests"]
        total = connection.get("totalCount", "?")
        nodes = _enrich_page_parallel(
            connection["nodes"], _enrich_pr, owner, repo, token
        )
        all_prs.extend(nodes)

        if connection["pageInfo"]["hasNextPage"]:
            cursor = connection["pageInfo"]["endCursor"]
        else:
            cursor = None

        if on_page:
            on_page(nodes, cursor)

        logger.info(
            "PRs: page %d — fetched %d/%s total", page_num, len(all_prs), total
        )

        if cursor is None:
            break

    return all_prs, cursor


def fetch_all_issues(
    owner: str,
    repo: str,
    token: str,
    start_cursor: str | None = None,
    on_page: PageCallback | None = None,
) -> tuple[list[dict], str | None]:
    """Fetch all issues (excluding PRs) with nested comments and timeline."""
    all_issues: list[dict] = []
    cursor = start_cursor
    page_num = 0

    while True:
        page_num += 1
        variables = {"owner": owner, "repo": repo, "cursor": cursor}
        data = graphql_request(ISSUE_QUERY, variables, token)

        connection = data["repository"]["issues"]
        total = connection.get("totalCount", "?")
        nodes = _enrich_page_parallel(
            connection["nodes"], _enrich_issue, owner, repo, token
        )
        all_issues.extend(nodes)

        if connection["pageInfo"]["hasNextPage"]:
            cursor = connection["pageInfo"]["endCursor"]
        else:
            cursor = None

        if on_page:
            on_page(nodes, cursor)

        logger.info(
            "Issues: page %d — fetched %d/%s total",
            page_num, len(all_issues), total,
        )

        if cursor is None:
            break

    return all_issues, cursor


def fetch_all_discussions(
    owner: str,
    repo: str,
    token: str,
    start_cursor: str | None = None,
    on_page: PageCallback | None = None,
) -> tuple[list[dict], str | None]:
    """Fetch all discussions with nested comments and replies."""
    all_discussions: list[dict] = []
    cursor = start_cursor
    page_num = 0

    while True:
        page_num += 1
        variables = {"owner": owner, "repo": repo, "cursor": cursor}
        data = graphql_request(DISCUSSION_QUERY, variables, token)

        connection = data["repository"]["discussions"]
        total = connection.get("totalCount", "?")
        nodes = _enrich_page_parallel(
            connection["nodes"], _enrich_discussion, owner, repo, token
        )
        all_discussions.extend(nodes)

        if connection["pageInfo"]["hasNextPage"]:
            cursor = connection["pageInfo"]["endCursor"]
        else:
            cursor = None

        if on_page:
            on_page(nodes, cursor)

        logger.info(
            "Discussions: page %d — fetched %d/%s total",
            page_num, len(all_discussions), total,
        )

        if cursor is None:
            break

    return all_discussions, cursor
