from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

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


@router.get("/decisions")
async def list_decisions(
    component: str | None = Query(None, description="Filter by component natural_key"),
    status: str | None = Query(None, description="Filter by status: accepted/superseded/proposed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = get_neo4j()

    where_clauses = []
    params: dict[str, Any] = {"lim": limit, "off": offset}

    if status:
        where_clauses.append("toLower(d.status) = toLower($status)")
        params["status"] = status

    if component:
        where_clauses.append(
            "EXISTS { MATCH (d)-[:DECISION_FOR]->(c:Component {natural_key: $comp}) }"
        )
        params["comp"] = component

    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    count_rows = db.read_query(f"MATCH (d:DesignDecision) {where} RETURN count(d) AS total", **params)
    total = count_rows[0]["total"] if count_rows else 0

    rows = db.read_query(
        f"""
        MATCH (d:DesignDecision)
        {where}
        OPTIONAL MATCH (d)-[:DECISION_FOR]->(comp:Component)
        OPTIONAL MATCH (d)-[:SUPERSEDES]->(older:DesignDecision)
        OPTIONAL MATCH (d)<-[:SUPERSEDES]-(newer:DesignDecision)
        RETURN
            d.natural_key AS natural_key,
            d.title AS title,
            d.status AS status,
            d.created_at AS event_time,
            d.evidence_excerpt AS evidence_excerpt,
            d.evidence_source AS source_key,
            collect(DISTINCT comp.natural_key) AS components,
            older.natural_key AS supersedes,
            newer.natural_key AS superseded_by
        ORDER BY d.created_at DESC
        SKIP $off LIMIT $lim
        """,
        **params,
    )

    decisions = []
    for row in rows:
        source_key = row.get("source_key") or ""
        decisions.append({
            "natural_key": row["natural_key"],
            "title": row.get("title"),
            "status": row.get("status"),
            "event_time": _to_str(row.get("event_time")),
            "evidence_excerpt": row.get("evidence_excerpt"),
            "source_key": source_key,
            "source_url": github_url(source_key),
            "components": [c for c in (row.get("components") or []) if c],
            "supersedes": row.get("supersedes"),
            "superseded_by": row.get("superseded_by"),
        })

    return {
        "decisions": decisions,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
