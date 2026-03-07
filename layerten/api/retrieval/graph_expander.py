from __future__ import annotations

import logging
from typing import Any

from layerten.process.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


def expand_candidate(
    db: Neo4jClient,
    natural_key: str,
    depth: int = 2,
    max_rels: int = 50,
) -> dict[str, Any]:
    """Traverse 1-2 hops from a candidate node, collecting claims with evidence."""
    rows = db.read_query(
        """
        MATCH (n {natural_key: $nk})-[r]-(m)
        RETURN
            n.natural_key AS subject,
            type(r) AS predicate,
            m.natural_key AS object,
            labels(m)[0] AS object_label,
            r.confidence AS confidence,
            r.evidence_excerpt AS evidence_excerpt,
            r.evidence_source AS evidence_source,
            r.event_time_from AS event_time,
            r.processing_time AS processing_time,
            m.title AS object_title,
            m.display_name AS object_display_name,
            startNode(r) = n AS outgoing
        ORDER BY r.confidence DESC
        LIMIT $lim
        """,
        nk=natural_key,
        lim=max_rels,
    )

    claims: list[dict] = []
    linked_entities: dict[str, dict] = {}

    for row in rows:
        obj_key = row["object"]
        is_outgoing = row["outgoing"]

        claim = {
            "direction": "outgoing" if is_outgoing else "incoming",
            "predicate": row["predicate"],
            "subject_key": natural_key if is_outgoing else obj_key,
            "object_key": obj_key if is_outgoing else natural_key,
            "confidence": row["confidence"],
            "evidence_excerpt": _to_str(row.get("evidence_excerpt")),
            "evidence_source": _to_str(row.get("evidence_source")),
            "event_time": _to_str(row.get("event_time")),
        }
        claims.append(claim)

        if obj_key and obj_key not in linked_entities:
            linked_entities[obj_key] = {
                "natural_key": obj_key,
                "type": row["object_label"],
                "display_name": row.get("object_display_name") or row.get("object_title") or obj_key,
            }

    if depth >= 2 and linked_entities:
        hop2_keys = [k for k in list(linked_entities.keys())[:10]
                     if not k.startswith("file:")]
        if hop2_keys:
            rows2 = db.read_query(
                """
                MATCH (n)-[r]-(m)
                WHERE n.natural_key IN $keys
                  AND NOT m.natural_key = $origin
                  AND r.evidence_excerpt IS NOT NULL
                RETURN
                    n.natural_key AS subject,
                    type(r) AS predicate,
                    m.natural_key AS object,
                    labels(m)[0] AS object_label,
                    r.confidence AS confidence,
                    r.evidence_excerpt AS evidence_excerpt,
                    r.evidence_source AS evidence_source,
                    r.event_time_from AS event_time,
                    m.title AS object_title,
                    m.display_name AS object_display_name,
                    startNode(r) = n AS outgoing
                ORDER BY r.confidence DESC
                LIMIT 30
                """,
                keys=hop2_keys,
                origin=natural_key,
            )
            for row in rows2:
                obj_key = row["object"]
                is_outgoing = row["outgoing"]
                claim = {
                    "direction": "outgoing" if is_outgoing else "incoming",
                    "predicate": row["predicate"],
                    "subject_key": row["subject"] if is_outgoing else obj_key,
                    "object_key": obj_key if is_outgoing else row["subject"],
                    "confidence": row["confidence"],
                    "evidence_excerpt": _to_str(row.get("evidence_excerpt")),
                    "evidence_source": _to_str(row.get("evidence_source")),
                    "event_time": _to_str(row.get("event_time")),
                    "hop": 2,
                }
                claims.append(claim)

                if obj_key and obj_key not in linked_entities:
                    linked_entities[obj_key] = {
                        "natural_key": obj_key,
                        "type": row["object_label"],
                        "display_name": row.get("object_display_name") or row.get("object_title") or obj_key,
                    }

    return {
        "claims": claims,
        "linked_entities": list(linked_entities.values()),
    }


def _to_str(val: Any) -> str | None:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)
