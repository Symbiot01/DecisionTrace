from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter

from layerten.api.main import get_neo4j
from layerten import config

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_str(val: Any) -> Any:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


@router.get("/stats")
async def get_stats():
    db = get_neo4j()

    node_rows = db.read_query(
        """
        MATCH (n)
        RETURN labels(n)[0] AS label, count(n) AS cnt
        ORDER BY cnt DESC
        """
    )
    node_counts = {row["label"]: row["cnt"] for row in node_rows}

    rel_rows = db.read_query(
        """
        MATCH ()-[r]->()
        RETURN type(r) AS rtype, count(r) AS cnt
        ORDER BY cnt DESC
        """
    )
    rel_counts = {row["rtype"]: row["cnt"] for row in rel_rows}

    checkpoint_index = 0
    total_events = 0
    try:
        cp_path = config.PROCESS_CHECKPOINT_PATH
        if cp_path.exists():
            with open(cp_path) as f:
                cp = json.load(f)
            checkpoint_index = cp.get("last_processed_index", 0)
        tl_path = config.UNIFIED_TIMELINE_PATH
        if tl_path.exists():
            with open(tl_path) as f:
                total_events = sum(1 for _ in f)
    except Exception:
        logger.warning("Could not read checkpoint/timeline info", exc_info=True)

    pct = round(checkpoint_index / total_events * 100, 1) if total_events else 0

    top_connected = db.read_query(
        """
        MATCH (n)
        WITH n, size([(n)-[]-() | 1]) AS degree
        ORDER BY degree DESC LIMIT 5
        RETURN n.natural_key AS natural_key, labels(n)[0] AS type, degree
        """
    )

    top_files = db.read_query(
        """
        MATCH (f:FileNode)<-[:MODIFIES]-(c:Commit)
        WITH f, count(c) AS commit_count
        ORDER BY commit_count DESC LIMIT 5
        RETURN f.path AS path, commit_count
        """
    )

    return {
        "nodes": node_counts,
        "relationships": rel_counts,
        "processing": {
            "checkpoint_index": checkpoint_index,
            "total_events": total_events,
            "percent_complete": pct,
        },
        "top_connected": [
            {"natural_key": r["natural_key"], "type": r["type"], "degree": r["degree"]}
            for r in top_connected
        ],
        "top_modified_files": [
            {"path": r["path"], "commit_count": r["commit_count"]}
            for r in top_files
        ],
    }
