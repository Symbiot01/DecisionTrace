from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from layerten.config import (
    PROCESS_CHECKPOINT_PATH,
    REPO_NAME,
    TARGET_REPO,
    UNIFIED_BRANCHES_PATH,
    UNIFIED_FILE_TREE_PATH,
    UNIFIED_LABELS_PATH,
    UNIFIED_PERSONS_PATH,
    UNIFIED_RENAMES_PATH,
    UNIFIED_TIMELINE_PATH,
)
from layerten.process.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


@dataclass
class ReferenceData:
    persons: dict = field(default_factory=dict)
    branches: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    renames: dict = field(default_factory=dict)
    file_tree: dict = field(default_factory=dict)
    timeline_index: dict = field(default_factory=dict)


def load_json(path: Path):
    if not path.exists():
        logger.warning("Reference file not found: %s", path)
        return {} if path.suffix == ".json" else []
    with open(path) as f:
        return json.load(f)


def load_reference_data() -> ReferenceData:
    """Load all reference data files into memory as lookup tables."""
    rd = ReferenceData()
    rd.persons = load_json(UNIFIED_PERSONS_PATH)
    rd.branches = load_json(UNIFIED_BRANCHES_PATH)
    rd.labels = load_json(UNIFIED_LABELS_PATH)
    rd.renames = load_json(UNIFIED_RENAMES_PATH)
    rd.file_tree = load_json(UNIFIED_FILE_TREE_PATH)
    logger.info(
        "Reference data loaded: %d persons, %d branches, %d labels, %d rename commits",
        len(rd.persons),
        len(rd.branches),
        len(rd.labels),
        len(rd.renames),
    )
    return rd


def build_timeline_index(timeline_path: Path = UNIFIED_TIMELINE_PATH) -> dict:
    """Build {natural_key: event} dict for lookups and cross-reference resolution."""
    index: dict = {}
    with open(timeline_path) as f:
        for line in f:
            event = json.loads(line)
            index[event["natural_key"]] = event
    logger.info("Timeline index built: %d entries", len(index))
    return index


def create_repository_node(neo4j: Neo4jClient):
    neo4j.upsert_node(
        "Repository",
        TARGET_REPO,
        {
            "name": REPO_NAME,
            "url": f"https://github.com/{TARGET_REPO}",
        },
    )
    logger.info("Repository node created/updated for %s", TARGET_REPO)


def load_checkpoint() -> int:
    """Return last_processed_index, or -1 if no checkpoint."""
    if PROCESS_CHECKPOINT_PATH.exists():
        with open(PROCESS_CHECKPOINT_PATH) as f:
            data = json.load(f)
        idx = data.get("last_processed_index", -1)
        logger.info("Checkpoint loaded: resuming from index %d", idx)
        return idx
    return -1


def save_checkpoint(index: int):
    with open(PROCESS_CHECKPOINT_PATH, "w") as f:
        json.dump({"last_processed_index": index}, f)


def clear_checkpoint():
    if PROCESS_CHECKPOINT_PATH.exists():
        PROCESS_CHECKPOINT_PATH.unlink()
        logger.info("Checkpoint cleared")


def stream_timeline(timeline_path: Path = UNIFIED_TIMELINE_PATH):
    """Yield events one at a time from the timeline JSONL file."""
    with open(timeline_path) as f:
        for line in f:
            yield json.loads(line)
