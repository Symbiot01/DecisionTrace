#!/usr/bin/env python3
"""Backfill is_current on DesignDecision nodes from SUPERSEDES edges.

Any node with an incoming SUPERSEDES edge is marked is_current=false.
Nodes that supersede others (and are not themselves superseded) become true.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from layerten import config  # noqa: E402
from layerten.process.neo4j_client import Neo4jClient  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db = Neo4jClient(
        config.NEO4J_URI,
        config.NEO4J_USERNAME,
        config.NEO4J_PASSWORD,
        config.NEO4J_DATABASE,
    )
    try:
        # Default: decisions with no supersession info are current
        r1 = db.run(
            """
            MATCH (d:DesignDecision)
            WHERE d.is_current IS NULL
            SET d.is_current = true
            RETURN count(d) AS n
            """
        )
        # Superseded nodes are not current
        r2 = db.run(
            """
            MATCH (newer:DesignDecision)-[:SUPERSEDES]->(older:DesignDecision)
            SET older.is_current = false
            RETURN count(DISTINCT older) AS n
            """
        )
        # Ensure superseding heads that are not themselves superseded stay current
        r3 = db.run(
            """
            MATCH (newer:DesignDecision)-[:SUPERSEDES]->(:DesignDecision)
            WHERE NOT EXISTS { MATCH (:DesignDecision)-[:SUPERSEDES]->(newer) }
            SET newer.is_current = true
            RETURN count(DISTINCT newer) AS n
            """
        )
        summary = {
            "null_to_true": r1[0]["n"] if r1 else 0,
            "marked_false": r2[0]["n"] if r2 else 0,
            "heads_true": r3[0]["n"] if r3 else 0,
        }
        logger.info("Backfill complete: %s", summary)
        print(summary)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
