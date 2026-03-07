from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query

from layerten.api.main import get_neo4j
from layerten.api.retrieval.question_parser import parse_question
from layerten.api.retrieval.candidate_recall import recall_candidates
from layerten.api.retrieval.graph_expander import expand_candidate
from layerten.api.retrieval.ranker import rank_results
from layerten.api.retrieval.formatter import format_result
from layerten.api.retrieval.answer_generator import generate_answer

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/ask")
async def ask(
    q: str = Query(..., description="Question to answer using evidence from the knowledge graph"),
    limit: int = Query(8, ge=1, le=20),
    min_confidence: float = Query(0.4, ge=0.0, le=1.0),
):
    """Retrieve evidence, generate an answer that cites sources [1], [2], etc., and return both."""
    t0 = time.time()
    db = get_neo4j()

    parsed = await parse_question(q)
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
    formatted_results = [format_result(i + 1, item) for i, item in enumerate(ranked)]

    answer = await generate_answer(q, formatted_results)

    processing_ms = int((time.time() - t0) * 1000)

    return {
        "question": q,
        "answer": answer,
        "sources": formatted_results,
        "metadata": {
            "sources_used": len(formatted_results),
            "processing_ms": processing_ms,
        },
    }
