from __future__ import annotations

import logging
from typing import Any

from layerten.process.neo4j_client import Neo4jClient
from layerten.api.retrieval.question_parser import ParsedQuestion

logger = logging.getLogger(__name__)


def _sanitize_lucene(term: str) -> str:
    """Escape Lucene special characters for full-text queries."""
    special = r'+-&|!(){}[]^"~*?:\/'
    out = []
    for ch in term:
        if ch in special:
            out.append(f"\\{ch}")
        else:
            out.append(ch)
    return "".join(out)


def recall_candidates(
    db: Neo4jClient,
    parsed: ParsedQuestion,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Gather candidate nodes via full-text index + direct key match + keyword fallback."""
    seen: dict[str, dict] = {}

    # 1. Direct entity ref match
    for ref in parsed.entity_refs:
        rows = db.read_query(
            "MATCH (n {natural_key: $nk}) RETURN labels(n)[0] AS label, properties(n) AS props",
            nk=ref,
        )
        for row in rows:
            nk = row["props"].get("natural_key", ref)
            if nk not in seen:
                seen[nk] = {"label": row["label"], "props": row["props"], "source": "direct"}

    # 2. Full-text index search
    if parsed.keywords:
        ft_terms = " OR ".join(_sanitize_lucene(k) for k in parsed.keywords if k)
        if ft_terms.strip():
            try:
                rows = db.read_query(
                    "CALL db.index.fulltext.queryNodes('search_nodes', $q) "
                    "YIELD node, score "
                    "RETURN labels(node)[0] AS label, properties(node) AS props, score "
                    "ORDER BY score DESC LIMIT $lim",
                    q=ft_terms,
                    lim=limit,
                )
                for row in rows:
                    nk = row["props"].get("natural_key", "")
                    if nk and nk not in seen:
                        seen[nk] = {
                            "label": row["label"],
                            "props": row["props"],
                            "source": "fulltext",
                            "ft_score": row["score"],
                        }
            except Exception:
                logger.warning("Full-text search failed, falling back to CONTAINS", exc_info=True)

    # 3. Keyword CONTAINS fallback (if full-text returned few results)
    if len(seen) < 5 and parsed.keywords:
        for kw in parsed.keywords[:3]:
            rows = db.read_query(
                "MATCH (n) WHERE n.title CONTAINS $kw OR n.body CONTAINS $kw "
                "OR n.message CONTAINS $kw OR n.evidence_excerpt CONTAINS $kw "
                "RETURN labels(n)[0] AS label, properties(n) AS props LIMIT 10",
                kw=kw,
            )
            for row in rows:
                nk = row["props"].get("natural_key", "")
                if nk and nk not in seen:
                    seen[nk] = {
                        "label": row["label"],
                        "props": row["props"],
                        "source": "contains",
                    }

    candidates = list(seen.values())[:limit]
    logger.info("Recall: %d candidates (%d direct, %d fulltext, %d contains)",
                len(candidates),
                sum(1 for c in candidates if c.get("source") == "direct"),
                sum(1 for c in candidates if c.get("source") == "fulltext"),
                sum(1 for c in candidates if c.get("source") == "contains"))
    return candidates
