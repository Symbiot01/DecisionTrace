import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from layerten.config import CHECKPOINT_PATH, RAW_EVENTS_PATH, TARGET_REPO

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()
_checkpoint_lock = threading.Lock()


class RepoMismatchError(RuntimeError):
    """Raised when the raw event log already holds a different repository."""


def write_raw_event(
    event_type: str,
    artifact_id: str,
    payload: dict,
    source: str = "github_api",
) -> None:
    RAW_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "id": f"{event_type}:{artifact_id}",
        "repo": TARGET_REPO,
        "event_type": event_type,
        "source": source,
        "artifact_id": artifact_id,
        "payload": payload,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    line = json.dumps(event, default=str) + "\n"
    with _write_lock:
        with open(RAW_EVENTS_PATH, "a") as f:
            f.write(line)


def get_fetched_ids(
    event_type: str | None = None, repo: str | None = None
) -> set[str]:
    """Return event IDs already fetched *for this repository*.

    Event IDs like ``pr:1`` are only unique within a repo. Scoping the dedup set
    by repo is what stops a fetch for repo B from treating repo A's artifacts as
    already fetched and skipping them.
    """
    if not RAW_EVENTS_PATH.exists():
        return set()
    repo = repo or TARGET_REPO
    ids: set[str] = set()
    with open(RAW_EVENTS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("repo") != repo:
                continue
            if event_type is None or obj.get("event_type") == event_type:
                ids.add(obj["id"])
    return ids


def scan_repos() -> dict[str, int]:
    """Count raw events per repository. Events written before repo stamping
    are reported under the ``"<unstamped>"`` key."""
    if not RAW_EVENTS_PATH.exists():
        return {}
    counts: dict[str, int] = {}
    with open(RAW_EVENTS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = obj.get("repo") or "<unstamped>"
            counts[key] = counts.get(key, 0) + 1
    return counts


def assert_single_repo(repo: str | None = None) -> None:
    """Fail closed if the raw event log mixes repositories.

    Fusing two repos produces a graph with cross-repo references that cannot be
    detected downstream, so this is checked before a fetch rather than after.
    """
    repo = repo or TARGET_REPO
    counts = scan_repos()
    foreign = {r: n for r, n in counts.items() if r != repo}
    if foreign:
        raise RepoMismatchError(
            f"{RAW_EVENTS_PATH} already contains events for {foreign!r} but "
            f"TARGET_REPO is {repo!r}. Fetching now would fuse repositories into "
            f"one graph. Move or delete the data directory first, or point "
            f"TARGET_REPO back at the existing repo."
        )


def count_events_by_type() -> dict[str, int]:
    """Count raw events grouped by event_type."""
    if not RAW_EVENTS_PATH.exists():
        return {}
    counts: dict[str, int] = {}
    with open(RAW_EVENTS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                et = obj.get("event_type", "unknown")
                counts[et] = counts.get(et, 0) + 1
            except json.JSONDecodeError:
                continue
    return counts


def save_checkpoint(source: str, cursor_data: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _checkpoint_lock:
        checkpoints = _load_all_checkpoints()
        checkpoints[source] = {
            **cursor_data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(CHECKPOINT_PATH, "w") as f:
            json.dump(checkpoints, f, indent=2)


def load_checkpoint(source: str) -> dict | None:
    with _checkpoint_lock:
        checkpoints = _load_all_checkpoints()
        return checkpoints.get(source)


def clear_checkpoint(source: str) -> None:
    with _checkpoint_lock:
        checkpoints = _load_all_checkpoints()
        checkpoints.pop(source, None)
        with open(CHECKPOINT_PATH, "w") as f:
            json.dump(checkpoints, f, indent=2)


def _load_all_checkpoints() -> dict:
    if not CHECKPOINT_PATH.exists():
        return {}
    try:
        with open(CHECKPOINT_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}
