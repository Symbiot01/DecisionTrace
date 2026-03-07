from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from layerten.api.main import get_neo4j

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/contributors")
async def list_contributors(limit: int = Query(20, ge=1, le=100)):
    db = get_neo4j()

    rows = db.read_query(
        """
        MATCH (p:Person)
        OPTIONAL MATCH (p)<-[:AUTHORED_BY]-(c:Commit)
        WITH p, count(c) AS commits
        OPTIONAL MATCH (p)<-[:AUTHORED_BY]-(pr:PullRequest)
        WITH p, commits, count(pr) AS prs
        OPTIONAL MATCH (p)<-[:REVIEWED_BY]-(rev)
        WITH p, commits, prs, count(rev) AS reviews
        OPTIONAL MATCH (p)<-[:AUTHORED_BY]-(iss:Issue)
        WITH p, commits, prs, reviews, count(iss) AS issues
        WITH p, commits, prs, reviews, issues, (commits + prs + reviews + issues) AS total
        ORDER BY total DESC
        LIMIT $lim
        OPTIONAL MATCH (p)<-[:AUTHORED_BY]-(authored_pr:PullRequest)-[:INTRODUCES]->(dd:DesignDecision)
        RETURN
            p.natural_key AS natural_key,
            p.display_name AS display_name,
            p.aliases AS aliases,
            commits, prs, reviews, issues, total,
            collect(DISTINCT {natural_key: dd.natural_key, title: dd.title}) AS decisions
        ORDER BY total DESC
        """,
        lim=limit,
    )

    contributors = []
    for row in rows:
        decisions = [d for d in (row.get("decisions") or []) if d.get("natural_key")]
        nk = row["natural_key"]
        login = nk.split(":", 1)[1] if ":" in nk else nk
        contributors.append({
            "natural_key": nk,
            "display_name": row.get("display_name") or login,
            "aliases": row.get("aliases") or [],
            "url": f"https://github.com/{login}",
            "stats": {
                "total_contributions": row["total"],
                "commits": row["commits"],
                "prs_authored": row["prs"],
                "reviews_given": row["reviews"],
                "issues_opened": row["issues"],
            },
            "decisions_introduced": decisions,
        })

    return {"contributors": contributors}
