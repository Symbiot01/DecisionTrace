import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DIFF_TRUNCATE_BYTES = 1_000_000  # 1 MB


def _run_git(args: list[str], cwd: str | Path | None = None) -> str:
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def _normalize_remote(url: str) -> str:
    """Compare remotes ignoring scheme, credentials, and a trailing .git."""
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    for prefix in ("https://", "http://", "ssh://", "git@"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    return cleaned.replace(":", "/").lower()


def clone_repo(repo_url: str, dest: Path) -> Path:
    """Clone with --mirror if fresh, or fetch --all if already exists."""
    if (dest / "HEAD").exists():
        # Reusing a clone of a *different* repo silently mixes two histories
        # into one graph, so verify the origin before fetching into it.
        existing = _run_git(["remote", "get-url", "origin"], cwd=dest).strip()
        if _normalize_remote(existing) != _normalize_remote(repo_url):
            raise RuntimeError(
                f"{dest} is a clone of {existing!r}, not {repo_url!r}. "
                f"Remove the directory or point TARGET_REPO at the existing repo."
            )
        logger.info("Repo already cloned at %s, fetching updates...", dest)
        _run_git(["fetch", "--all"], cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Cloning %s into %s ...", repo_url, dest)
        _run_git(["clone", "--mirror", repo_url, str(dest)])
    return dest


# Use null byte as separator — git's %x00 outputs \0 which can't appear in text fields
_LOG_FORMAT = "%H%x00%P%x00%an%x00%ae%x00%cn%x00%ce%x00%aI%x00%s"


def extract_commits(repo_path: Path) -> list[dict]:
    """Extract metadata for every commit in the repo."""
    raw = _run_git(
        ["log", "--all", "--format=" + _LOG_FORMAT],
        cwd=repo_path,
    )
    commits = []
    for line in raw.strip().splitlines():
        if not line:
            continue
        parts = line.split("\x00", 7)
        if len(parts) < 8:
            logger.warning("Skipping malformed log line: %s", line[:120])
            continue
        sha, parents, aname, aemail, cname, cemail, ts, subject = parts
        commits.append({
            "sha": sha,
            "parent_shas": parents.split() if parents else [],
            "author_name": aname,
            "author_email": aemail,
            "committer_name": cname,
            "committer_email": cemail,
            "committed_at": ts,
            "message": subject,
        })
    return commits


def extract_commit_full_message(repo_path: Path, sha: str) -> str:
    """Get the full commit message (subject + body)."""
    return _run_git(["log", "-1", "--format=%B", sha], cwd=repo_path).strip()


def extract_commit_diff(repo_path: Path, sha: str) -> tuple[str, bool]:
    """Return (patch_text, was_truncated) for one commit."""
    try:
        result = subprocess.run(
            ["git", "diff-tree", "-p", "--no-color", sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        patch = result.stdout
    except subprocess.TimeoutExpired:
        logger.warning("Diff timed out for %s", sha)
        return "", True

    if len(patch.encode("utf-8", errors="replace")) > DIFF_TRUNCATE_BYTES:
        truncated = patch[: DIFF_TRUNCATE_BYTES // 2]
        return truncated, True
    return patch, False


def extract_commit_files(repo_path: Path, sha: str) -> list[dict]:
    """List files changed in a commit with status (A/M/D/R/C)."""
    raw = _run_git(
        ["diff-tree", "--no-commit-id", "-r", "--name-status", sha],
        cwd=repo_path,
    )
    files = []
    for line in raw.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") or status.startswith("C"):
            files.append({
                "status": status[0],
                "old_path": parts[1],
                "new_path": parts[2],
            })
        else:
            files.append({
                "status": status[0],
                "path": parts[1] if len(parts) > 1 else "",
            })
    return files


def extract_file_tree(repo_path: Path, ref: str = "HEAD") -> list[str]:
    """List all file paths at a given ref."""
    raw = _run_git(["ls-tree", "-r", "--name-only", ref], cwd=repo_path)
    return [p for p in raw.strip().splitlines() if p]


def extract_renames(repo_path: Path) -> list[dict]:
    """Detect file renames across the full history."""
    raw = _run_git(
        [
            "log",
            "--all",
            "--diff-filter=R",
            "--name-status",
            "--format=%H %aI",
        ],
        cwd=repo_path,
    )
    renames = []
    current_sha = ""
    current_ts = ""
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith("R"):
            parts = line.split(" ", 1)
            if len(parts) == 2 and len(parts[0]) == 40:
                current_sha = parts[0]
                current_ts = parts[1]
        else:
            tab_parts = line.split("\t")
            if len(tab_parts) >= 3:
                renames.append({
                    "commit_sha": current_sha,
                    "committed_at": current_ts,
                    "old_path": tab_parts[1],
                    "new_path": tab_parts[2],
                })
    return renames


def extract_tags(repo_path: Path) -> list[dict]:
    """List all tags with their target commit SHAs."""
    raw = _run_git(["tag", "-l"], cwd=repo_path)
    tags = []
    for tag_name in raw.strip().splitlines():
        tag_name = tag_name.strip()
        if not tag_name:
            continue
        try:
            sha = _run_git(
                ["rev-parse", f"{tag_name}^{{commit}}"],
                cwd=repo_path,
            ).strip()
        except RuntimeError:
            sha = _run_git(["rev-parse", tag_name], cwd=repo_path).strip()
        tags.append({"name": tag_name, "commit_sha": sha})
    return tags
