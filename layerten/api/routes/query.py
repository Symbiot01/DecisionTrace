from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query

from layerten.api.main import get_neo4j
from layerten.api.retrieval.question_parser import parse_question
from layerten.api.retrieval.candidate_recall import recall_candidates
from layerten.api.retrieval.graph_expander import expand_candidate
from layerten.api.retrieval.ranker import rank_results
from layerten.api.retrieval.formatter import format_context_pack

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/query")
async def query_graph(
    q: str = Query(..., description="Natural language question"),
    limit: int = Query(10, ge=1, le=50),
    min_confidence: float = Query(0.4, ge=0.0, le=1.0),
):
    t0 = time.time()
    db = get_neo4j()

    parsed = await parse_question(q)
    logger.info("Parsed: intent=%s keywords=%s refs=%s", parsed.intent, parsed.keywords, parsed.entity_refs)

    candidates = recall_candidates(db, parsed, limit=limit * 5)

    expanded: dict = {}
    for cand in candidates:
        nk = cand["props"].get("natural_key", "")
        if nk:
            expanded[nk] = expand_candidate(db, nk, depth=2)

    ranked = rank_results(
        candidates, expanded, parsed.keywords,
        limit=limit, min_confidence=min_confidence, intent=parsed.intent,
    )

    processing_ms = int((time.time() - t0) * 1000)

    return format_context_pack(
        question=q,
        intent=parsed.intent,
        ranked=ranked,
        total_candidates=len(candidates),
        processing_ms=processing_ms,
        db=db,
    )
