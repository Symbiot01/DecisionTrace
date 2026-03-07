from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from layerten.api.main import get_neo4j

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_str(val: Any) -> Any:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


@router.get("/graph/overview")
async def graph_overview(max_nodes: int = Query(100, ge=10, le=500)):
    """Sampled subgraph: all Components + their DesignDecisions + connected PRs/Persons."""
    db = get_neo4j()

    rows = db.read_query(
        """
        MATCH (c:Component)
        OPTIONAL MATCH (c)<-[r1]-(related)
        WITH c, related, r1
        LIMIT $lim
        RETURN
            c.natural_key AS c_key, c.title AS c_title,
            related.natural_key AS r_key, labels(related)[0] AS r_label,
            related.title AS r_title, related.display_name AS r_display_name,
            type(r1) AS rel_type,
            r1.confidence AS confidence,
            r1.event_time_from AS event_time,
            r1.evidence_excerpt AS evidence_excerpt
        """,
        lim=max_nodes * 3,
    )

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    for row in rows:
        c_key = row["c_key"]
        if c_key not in nodes:
            nodes[c_key] = {
                "id": c_key,
                "label": "Component",
                "title": row.get("c_title") or c_key,
                "degree": 0,
            }

        r_key = row.get("r_key")
        if r_key and r_key not in nodes:
            nodes[r_key] = {
                "id": r_key,
                "label": row.get("r_label", ""),
                "title": row.get("r_title") or row.get("r_display_name") or r_key,
                "degree": 0,
            }

        if r_key and row.get("rel_type"):
            nodes[c_key]["degree"] = nodes[c_key].get("degree", 0) + 1
            nodes[r_key]["degree"] = nodes[r_key].get("degree", 0) + 1
            edges.append({
                "source": r_key,
                "target": c_key,
                "type": row["rel_type"],
                "confidence": row.get("confidence"),
                "event_time": _to_str(row.get("event_time")),
                "evidence_excerpt": row.get("evidence_excerpt"),
            })

    node_list = sorted(nodes.values(), key=lambda n: n.get("degree", 0), reverse=True)[:max_nodes]
    kept_ids = {n["id"] for n in node_list}
    edge_list = [e for e in edges if e["source"] in kept_ids and e["target"] in kept_ids]

    return {
        "nodes": node_list,
        "edges": edge_list,
        "metadata": {
            "total_nodes": len(node_list),
            "total_edges": len(edge_list),
            "sampled": len(nodes) > max_nodes,
        },
    }


@router.get("/graph/neighborhood/{natural_key:path}")
async def graph_neighborhood(
    natural_key: str,
    depth: int = Query(2, ge=1, le=3),
    max_nodes: int = Query(50, ge=5, le=200),
):
    """Subgraph around a specific node."""
    db = get_neo4j()

    rows = db.read_query(
        f"""
        MATCH path = (center {{natural_key: $nk}})-[*1..{depth}]-(neighbor)
        WITH center, neighbor, relationships(path) AS rels
        UNWIND rels AS r
        WITH center, neighbor, r, startNode(r) AS sn, endNode(r) AS en
        RETURN DISTINCT
            sn.natural_key AS source,
            labels(sn)[0] AS source_label,
            sn.title AS source_title,
            sn.display_name AS source_display_name,
            en.natural_key AS target,
            labels(en)[0] AS target_label,
            en.title AS target_title,
            en.display_name AS target_display_name,
            type(r) AS rel_type,
            r.confidence AS confidence,
            r.event_time_from AS event_time,
            r.evidence_excerpt AS evidence_excerpt
        LIMIT $lim
        """,
        nk=natural_key,
        lim=max_nodes * 5,
    )

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    for row in rows:
        for prefix in ("source", "target"):
            nk = row[prefix]
            if nk and nk not in nodes:
                nodes[nk] = {
                    "id": nk,
                    "label": row[f"{prefix}_label"],
                    "title": row.get(f"{prefix}_title") or row.get(f"{prefix}_display_name") or nk,
                    "degree": 0,
                }

        src, tgt = row["source"], row["target"]
        if src and tgt:
            nodes.get(src, {})["degree"] = nodes.get(src, {}).get("degree", 0) + 1
            nodes.get(tgt, {})["degree"] = nodes.get(tgt, {}).get("degree", 0) + 1
            edges.append({
                "source": src,
                "target": tgt,
                "type": row["rel_type"],
                "confidence": row.get("confidence"),
                "event_time": _to_str(row.get("event_time")),
                "evidence_excerpt": row.get("evidence_excerpt"),
            })

    node_list = sorted(nodes.values(), key=lambda n: n.get("degree", 0), reverse=True)[:max_nodes]
    kept_ids = {n["id"] for n in node_list}
    edge_list = [e for e in edges if e["source"] in kept_ids and e["target"] in kept_ids]

    return {
        "nodes": node_list,
        "edges": edge_list,
        "metadata": {
            "total_nodes": len(node_list),
            "total_edges": len(edge_list),
            "sampled": len(nodes) > max_nodes,
        },
    }
