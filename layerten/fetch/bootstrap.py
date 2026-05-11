"""
Main orchestrator: fetches all historical data from a GitHub repo.

Usage:
    python -m layerten.fetch.bootstrap
"""

from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from layerten.config import (
    GITHUB_TOKEN,
    RAW_EVENTS_PATH,
    REPO_CLONE_DIR,
    REPO_NAME,
    REPO_OWNER,
    TARGET_REPO,
)
from layerten.fetch.clone import (
    clone_repo,
    extract_commit_diff,
    extract_commit_files,
    extract_commit_full_message,
    extract_commits,
    extract_file_tree,
    extract_renames,
    extract_tags,
)
from layerten.fetch.graphql import (
    fetch_all_discussions,
    fetch_all_issues,
    fetch_all_prs,
)
from layerten.fetch.http_client import close_clients
from layerten.fetch.rest import (
    fetch_branches,
    fetch_commits_metadata,
    fetch_labels,
    fetch_releases,
)
from layerten.store.raw_events import (
    assert_single_repo,
    clear_checkpoint,
    count_events_by_type,
    get_fetched_ids,
    load_checkpoint,
    save_checkpoint,
    write_raw_event,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

COMMIT_CHECKPOINT_INTERVAL = 500


def _step_clone():
    """Step 1: Clone the repo (or fetch updates)."""
    repo_url = f"https://github.com/{TARGET_REPO}.git"
    clone_repo(repo_url, REPO_CLONE_DIR)
    logger.info("Clone complete: %s", REPO_CLONE_DIR)


def _step_commits():
    """Step 2: Extract commits + diffs from the local clone."""
    fetched = get_fetched_ids("commit_clone")
    commits = extract_commits(REPO_CLONE_DIR)
    total = len(commits)
    logger.info("Found %d commits in clone", total)

    checkpoint = load_checkpoint("commits_clone")
    start_idx = checkpoint.get("last_index", 0) if checkpoint else 0

    for i, commit in enumerate(commits):
        if i < start_idx:
            continue
        event_id = f"commit_clone:{commit['sha']}"
        if event_id in fetched:
            continue

        full_message = extract_commit_full_message(REPO_CLONE_DIR, commit["sha"])
        diff, truncated = extract_commit_diff(REPO_CLONE_DIR, commit["sha"])
        files_changed = extract_commit_files(REPO_CLONE_DIR, commit["sha"])

        payload = {
            **commit,
            "message": full_message,
            "diff": diff,
            "diff_truncated": truncated,
            "files_changed": files_changed,
        }
        write_raw_event("commit_clone", commit["sha"], payload, source="git_clone")

        if (i + 1) % COMMIT_CHECKPOINT_INTERVAL == 0:
            save_checkpoint("commits_clone", {"last_index": i + 1})
            logger.info("Commits: %d / %d extracted", i + 1, total)

    clear_checkpoint("commits_clone")
    logger.info("Commits: all %d extracted", total)


def _step_file_tree():
    """Step 3: Extract the file tree at HEAD."""
    fetched = get_fetched_ids("file_tree")
    if "file_tree:HEAD" in fetched:
        logger.info("File tree at HEAD already fetched, skipping")
        return

    tree = extract_file_tree(REPO_CLONE_DIR, "HEAD")
    write_raw_event("file_tree", "HEAD", {"ref": "HEAD", "files": tree}, source="git_clone")
    logger.info("File tree at HEAD: %d files", len(tree))


def _step_renames():
    """Step 4: Extract rename history."""
    fetched = get_fetched_ids("rename")
    if "rename:all" in fetched:
        logger.info("Renames already fetched, skipping")
        return

    renames = extract_renames(REPO_CLONE_DIR)
    write_raw_event("rename", "all", {"renames": renames}, source="git_clone")
    logger.info("Renames: %d detected across history", len(renames))


def _step_tags():
    """Step 5: Extract tags."""
    fetched = get_fetched_ids("tag")
    tags = extract_tags(REPO_CLONE_DIR)
    new_count = 0
    for tag in tags:
        eid = f"tag:{tag['name']}"
        if eid in fetched:
            continue
        write_raw_event("tag", tag["name"], tag, source="git_clone")
        new_count += 1
    logger.info("Tags: %d total, %d new", len(tags), new_count)


def _step_branches():
    """Step 6: Fetch branches from REST API."""
    fetched = get_fetched_ids("branch")
    branches = fetch_branches(REPO_OWNER, REPO_NAME, GITHUB_TOKEN)
    new_count = 0
    for b in branches:
        eid = f"branch:{b['name']}"
        if eid in fetched:
            continue
        write_raw_event("branch", b["name"], b, source="github_api")
        new_count += 1
    logger.info("Branches: %d total, %d new", len(branches), new_count)


def _step_labels():
    """Step 7: Fetch labels from REST API."""
    fetched = get_fetched_ids("label")
    labels = fetch_labels(REPO_OWNER, REPO_NAME, GITHUB_TOKEN)
    new_count = 0
    for label in labels:
        eid = f"label:{label['name']}"
        if eid in fetched:
            continue
        write_raw_event("label", label["name"], label, source="github_api")
        new_count += 1
    logger.info("Labels: %d total, %d new", len(labels), new_count)


def _step_releases():
    """Step 8: Fetch releases from REST API."""
    fetched = get_fetched_ids("release")
    releases = fetch_releases(REPO_OWNER, REPO_NAME, GITHUB_TOKEN)
    new_count = 0
    for r in releases:
        eid = f"release:{r['tag_name']}"
        if eid in fetched:
            continue
        write_raw_event("release", r["tag_name"], r, source="github_api")
        new_count += 1
    logger.info("Releases: %d total, %d new", len(releases), new_count)


def _step_commits_metadata():
    """Step 9: Fetch commit metadata from REST API (author login, verified)."""
    fetched = get_fetched_ids("commit_api")
    commits = fetch_commits_metadata(REPO_OWNER, REPO_NAME, GITHUB_TOKEN)
    new_count = 0
    for c in commits:
        eid = f"commit_api:{c['sha']}"
        if eid in fetched:
            continue
        write_raw_event("commit_api", c["sha"], c, source="github_api")
        new_count += 1
    logger.info("Commit metadata (API): %d total, %d new", len(commits), new_count)


def _make_graphql_page_handler(
    event_type: str,
    checkpoint_key: str,
    fetched: set[str],
    counters: dict[str, int],
):
    """Write each page to raw events and persist resume cursor."""

    def on_page(nodes: list[dict], resume_cursor: str | None) -> None:
        for node in nodes:
            artifact_id = str(node["number"])
            eid = f"{event_type}:{artifact_id}"
            counters["fetched"] += 1
            if eid in fetched:
                continue
            write_raw_event(event_type, artifact_id, node, source="github_api")
            fetched.add(eid)
            counters["new"] += 1

        if resume_cursor:
            save_checkpoint(checkpoint_key, {"cursor": resume_cursor})
        else:
            clear_checkpoint(checkpoint_key)

    return on_page


def _step_prs():
    """Fetch all PRs via GraphQL (incremental write + cursor checkpoint)."""
    fetched = get_fetched_ids("pr")
    checkpoint = load_checkpoint("prs_graphql")
    start_cursor = checkpoint.get("cursor") if checkpoint else None
    counters = {"fetched": 0, "new": 0}

    prs, _ = fetch_all_prs(
        REPO_OWNER,
        REPO_NAME,
        GITHUB_TOKEN,
        start_cursor,
        on_page=_make_graphql_page_handler(
            "pr", "prs_graphql", fetched, counters
        ),
    )
    clear_checkpoint("prs_graphql")
    logger.info(
        "Pull Requests: %d fetched, %d new",
        counters["fetched"] or len(prs),
        counters["new"],
    )


def _step_issues():
    """Fetch all issues via GraphQL (incremental write + cursor checkpoint)."""
    fetched = get_fetched_ids("issue")
    checkpoint = load_checkpoint("issues_graphql")
    start_cursor = checkpoint.get("cursor") if checkpoint else None
    counters = {"fetched": 0, "new": 0}

    issues, _ = fetch_all_issues(
        REPO_OWNER,
        REPO_NAME,
        GITHUB_TOKEN,
        start_cursor,
        on_page=_make_graphql_page_handler(
            "issue", "issues_graphql", fetched, counters
        ),
    )
    clear_checkpoint("issues_graphql")
    logger.info(
        "Issues: %d fetched, %d new",
        counters["fetched"] or len(issues),
        counters["new"],
    )


def _step_discussions():
    """Fetch all discussions via GraphQL (incremental write + cursor checkpoint)."""
    fetched = get_fetched_ids("discussion")
    checkpoint = load_checkpoint("discussions_graphql")
    start_cursor = checkpoint.get("cursor") if checkpoint else None
    counters = {"fetched": 0, "new": 0}

    discussions, _ = fetch_all_discussions(
        REPO_OWNER,
        REPO_NAME,
        GITHUB_TOKEN,
        start_cursor,
        on_page=_make_graphql_page_handler(
            "discussion", "discussions_graphql", fetched, counters
        ),
    )
    clear_checkpoint("discussions_graphql")
    logger.info(
        "Discussions: %d fetched, %d new",
        counters["fetched"] or len(discussions),
        counters["new"],
    )


def _print_summary(elapsed: float):
    """Print final summary of what was fetched."""
    counts = count_events_by_type()
    total = sum(counts.values())

    file_size_mb = 0.0
    if RAW_EVENTS_PATH.exists():
        file_size_mb = RAW_EVENTS_PATH.stat().st_size / (1024 * 1024)

    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)
    print(f"  Time elapsed:  {elapsed:.1f}s ({elapsed / 60:.1f}m)")
    print(f"  Raw log size:  {file_size_mb:.1f} MB")
    print(f"  Total events:  {total}")
    print()
    for et, count in sorted(counts.items()):
        print(f"  {et:20s}  {count:>6}")
    print("=" * 60)


# Sequential steps before GraphQL fan-out
PRE_GRAPHQL_STEPS = [
    ("Clone repo", _step_clone),
    ("Extract commits + diffs", _step_commits),
    ("Extract file tree at HEAD", _step_file_tree),
    ("Extract renames", _step_renames),
    ("Extract tags", _step_tags),
    ("Fetch branches (REST)", _step_branches),
    ("Fetch labels (REST)", _step_labels),
    ("Fetch releases (REST)", _step_releases),
    ("Fetch commit metadata (REST)", _step_commits_metadata),
]

GRAPHQL_STEPS = [
    ("Fetch PRs (GraphQL)", _step_prs),
    ("Fetch issues (GraphQL)", _step_issues),
    ("Fetch discussions (GraphQL)", _step_discussions),
]

# Back-compat for anything that inspects STEPS
STEPS = PRE_GRAPHQL_STEPS + GRAPHQL_STEPS


def _run_step(index: int, total: int, name: str, step_fn) -> None:
    logger.info("─── Step %d/%d: %s ───", index, total, name)
    step_start = time.time()
    try:
        step_fn()
    except Exception:
        logger.exception("Step %d (%s) failed", index, name)
        raise
    logger.info("Step %d done in %.1fs", index, time.time() - step_start)


def run_bootstrap():
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN not set in .env — aborting")
        sys.exit(1)

    assert_single_repo()

    logger.info("Starting bootstrap for %s", TARGET_REPO)
    start = time.time()
    total_steps = len(PRE_GRAPHQL_STEPS) + len(GRAPHQL_STEPS)

    try:
        for i, (name, step_fn) in enumerate(PRE_GRAPHQL_STEPS, 1):
            _run_step(i, total_steps, name, step_fn)

        # Overlap PR / issue / discussion GraphQL fetches
        gql_start = len(PRE_GRAPHQL_STEPS) + 1
        logger.info(
            "─── Steps %d–%d: GraphQL PRs/issues/discussions (parallel) ───",
            gql_start,
            total_steps,
        )
        parallel_start = time.time()
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(_run_step, gql_start + offset, total_steps, name, step_fn): name
                for offset, (name, step_fn) in enumerate(GRAPHQL_STEPS)
            }
            errors: list[tuple[str, BaseException]] = []
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    fut.result()
                except BaseException as exc:  # noqa: BLE001 — surface all worker failures
                    errors.append((name, exc))
            if errors:
                for name, exc in errors:
                    logger.error("GraphQL step failed: %s: %s", name, exc)
                raise errors[0][1]

        logger.info(
            "Parallel GraphQL steps done in %.1fs",
            time.time() - parallel_start,
        )
    finally:
        close_clients()

    elapsed = time.time() - start
    _print_summary(elapsed)


if __name__ == "__main__":
    run_bootstrap()
