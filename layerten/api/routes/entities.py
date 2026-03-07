from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from layerten.api.main import get_neo4j
from layerten.api.retrieval.formatter import github_url

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_str(val: Any) -> Any:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _clean_props(props: dict) -> dict:
    return {k: _to_str(v) for k, v in props.items()}


@router.get("/entity/{natural_key:path}")
async def get_entity(natural_key: str):
    db = get_neo4j()

    rows = db.read_query(
        "MATCH (n {natural_key: $nk}) RETURN labels(n)[0] AS label, properties(n) AS props",
        nk=natural_key,
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Entity not found: {natural_key}")

    entity_label = rows[0]["label"]
    entity_props = _clean_props(rows[0]["props"])

    claims = _get_claims(db, natural_key)

    supersession_chain = None
    if entity_label == "DesignDecision":
        supersession_chain = _get_supersession_chain(db, natural_key)

    rename_chain = None
    if entity_label == "FileNode":
        rename_chain = _get_rename_chain(db, natural_key)

    return {
        "entity": {
            "type": entity_label,
            "natural_key": natural_key,
            "properties": entity_props,
            "url": github_url(natural_key),
        },
        "claims": claims,
        "supersession_chain": supersession_chain,
        "rename_chain": rename_chain,
    }


def _get_claims(db, natural_key: str) -> list[dict]:
    rows = db.read_query(
        """
        MATCH (n {natural_key: $nk})-[r]-(m)
        RETURN
            type(r) AS predicate,
            m.natural_key AS other_key,
            labels(m)[0] AS other_label,
            m.title AS other_title,
            m.display_name AS other_display_name,
            r.confidence AS confidence,
            r.evidence_excerpt AS evidence_excerpt,
            r.evidence_source AS evidence_source,
            r.event_time_from AS event_time,
            startNode(r) = n AS outgoing
        ORDER BY r.event_time_from DESC, r.processing_time DESC
        """,
        nk=natural_key,
    )
    claims = []
    for row in rows:
        claims.append({
            "direction": "outgoing" if row["outgoing"] else "incoming",
            "predicate": row["predicate"],
            "other_entity": {
                "natural_key": row["other_key"],
                "type": row["other_label"],
                "title": row.get("other_title") or row.get("other_display_name") or row["other_key"],
            },
            "evidence_excerpt": _to_str(row.get("evidence_excerpt")),
            "confidence": row.get("confidence"),
            "event_time": _to_str(row.get("event_time")),
            "source_url": github_url(row.get("evidence_source") or ""),
        })
    return claims


def _get_supersession_chain(db, natural_key: str) -> list[dict]:
    """Walk SUPERSEDES edges backward and forward to build the decision chain."""
    rows = db.read_query(
        """
        MATCH chain = (start)-[:SUPERSEDES*0..10]->(end)
        WHERE $nk IN [n IN nodes(chain) | n.natural_key]
        UNWIND nodes(chain) AS node
        RETURN DISTINCT
            node.natural_key AS nk,
            node.title AS title,
            node.status AS status,
            node.created_at AS event_time
        ORDER BY node.created_at
        """,
        nk=natural_key,
    )
    return [
        {
            "natural_key": r["nk"],
            "title": r.get("title"),
            "status": r.get("status"),
            "event_time": _to_str(r.get("event_time")),
        }
        for r in rows
    ]


def _get_rename_chain(db, natural_key: str) -> list[dict]:
    """Walk RENAMES edges to build the file rename chain."""
    rows = db.read_query(
        """
        MATCH chain = (start)-[:RENAMES*0..20]->(end)
        WHERE $nk IN [n IN nodes(chain) | n.natural_key]
        UNWIND nodes(chain) AS node
        RETURN DISTINCT
            node.natural_key AS nk,
            node.path AS path
        ORDER BY node.created_at
        """,
        nk=natural_key,
    )
    return [{"natural_key": r["nk"], "path": r.get("path")} for r in rows]
