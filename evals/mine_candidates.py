#!/usr/bin/env python3
"""Mine gold-set candidates from Neo4j + timeline.jsonl (read-only, no LLM).

Emits evals/candidates.jsonl and evals/span_alignment.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from layerten import config  # noqa: E402
from layerten.process.neo4j_client import Neo4jClient  # noqa: E402
from layerten.process.tools.validator import validate_read_only_cypher  # noqa: E402

logger = logging.getLogger(__name__)

SOURCE_PREFIXES = ("pr:", "issue:", "commit:", "tag:", "discussion:")
CLOSES_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE
)


def _read_query(db: Neo4jClient, cypher: str, **params: Any) -> list[dict]:
    validate_read_only_cypher(cypher)
    return db.read_query(cypher, **params)


def _load_timeline_index(path: Path) -> dict[str, dict]:
    """Map natural_key -> event for span checks and structural mining."""
    index: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            ev = json.loads(line)
            nk = ev.get("natural_key")
            if nk:
                index[nk] = ev
    return index


def _artifact_text(ev: dict) -> str:
    parts = [
        ev.get("title") or "",
        ev.get("body") or "",
        ev.get("message") or "",
        ev.get("release_body") or "",
        ev.get("release_name") or "",
    ]
    for c in ev.get("comments") or []:
        if isinstance(c, dict):
            parts.append(c.get("body") or "")
        elif isinstance(c, str):
            parts.append(c)
    return "\n".join(p for p in parts if p)


def _span_ok(excerpt: str, source_text: str) -> bool:
    if not excerpt or not source_text:
        return False
    # Normalize whitespace for brittle PDF/diff excerpts
    norm_ex = " ".join(excerpt.split())
    norm_src = " ".join(source_text.split())
    if norm_ex and norm_ex in norm_src:
        return True
    # Allow short excerpts that appear as contiguous substring ignoring case
    if len(norm_ex) >= 20 and norm_ex.lower() in norm_src.lower():
        return True
    return False


def mine_fact(db: Neo4jClient, limit: int) -> list[dict]:
    rows = _read_query(
        db,
        """
        MATCH (d:DesignDecision)
        WHERE d.evidence_excerpt IS NOT NULL
          AND trim(d.evidence_excerpt) <> ''
          AND d.evidence_source IS NOT NULL
          AND trim(d.evidence_source) <> ''
        RETURN d.natural_key AS decision_key,
               d.title AS title,
               d.evidence_excerpt AS excerpt,
               d.evidence_source AS evidence_source,
               d.status AS status,
               coalesce(d.is_current, true) AS is_current
        ORDER BY d.created_at DESC
        LIMIT $lim
        """,
        lim=limit,
    )
    out = []
    for row in rows:
        src = row.get("evidence_source") or ""
        if not src.startswith(SOURCE_PREFIXES):
            continue
        out.append(
            {
                "slice": "fact",
                "decision_key": row["decision_key"],
                "title": row.get("title"),
                "excerpt": row.get("excerpt"),
                "evidence_source": src,
                "status": row.get("status"),
                "is_current": row.get("is_current"),
                "gold_source_keys": [src],
                "gold_entity_keys": [row["decision_key"]],
                "forbidden_keys": [],
                "must_refuse": False,
            }
        )
    return out


def mine_current(db: Neo4jClient, limit: int) -> list[dict]:
    rows = _read_query(
        db,
        """
        MATCH (newer:DesignDecision)-[:SUPERSEDES]->(older:DesignDecision)
        RETURN newer.natural_key AS newer_key,
               newer.title AS newer_title,
               newer.evidence_source AS newer_source,
               older.natural_key AS older_key,
               older.title AS older_title,
               older.evidence_source AS older_source
        LIMIT $lim
        """,
        lim=limit,
    )
    out = []
    for row in rows:
        gold = [row["newer_key"]]
        if row.get("newer_source"):
            gold.append(row["newer_source"])
        out.append(
            {
                "slice": "current",
                "newer_key": row["newer_key"],
                "newer_title": row.get("newer_title"),
                "older_key": row["older_key"],
                "older_title": row.get("older_title"),
                "gold_source_keys": gold,
                "gold_entity_keys": [row["newer_key"]],
                "forbidden_keys": [row["older_key"]],
                "must_refuse": False,
            }
        )
    return out


def mine_structural(db: Neo4jClient, timeline: dict[str, dict], limit: int) -> list[dict]:
    out: list[dict] = []

    closes_rows = _read_query(
        db,
        """
        MATCH (a)-[r:CLOSES]->(b)
        RETURN a.natural_key AS subject,
               b.natural_key AS object,
               r.evidence_excerpt AS excerpt,
               coalesce(r.evidence_source, a.natural_key) AS evidence_source
        LIMIT $lim
        """,
        lim=limit,
    )
    for row in closes_rows:
        out.append(
            {
                "slice": "structural",
                "kind": "closes",
                "subject": row["subject"],
                "object": row["object"],
                "gold_source_keys": [row["subject"], row["object"]],
                "gold_entity_keys": [row["subject"], row["object"]],
                "forbidden_keys": [],
                "must_refuse": False,
                "evidence_source": row.get("evidence_source"),
            }
        )

    # Cross-check a few closes patterns from timeline messages
    checked = 0
    for nk, ev in timeline.items():
        if checked >= limit:
            break
        if ev.get("type") != "commit":
            continue
        msg = ev.get("message") or ""
        m = CLOSES_RE.search(msg)
        if not m:
            continue
        num = m.group(1)
        issue_key = f"issue:{num}"
        pr_key = f"pr:{num}"
        obj = issue_key if issue_key in timeline else (pr_key if pr_key in timeline else None)
        if not obj:
            continue
        out.append(
            {
                "slice": "structural",
                "kind": "closes_timeline",
                "subject": nk,
                "object": obj,
                "gold_source_keys": [nk, obj],
                "gold_entity_keys": [nk, obj],
                "forbidden_keys": [],
                "must_refuse": False,
                "message_excerpt": msg[:200],
            }
        )
        checked += 1

    authored = _read_query(
        db,
        """
        MATCH (c:Commit)-[:AUTHORED_BY]->(p:Person)
        RETURN c.natural_key AS commit_key,
               c.message AS message,
               p.natural_key AS person_key,
               coalesce(p.display_name, p.login, p.natural_key) AS person_name
        LIMIT $lim
        """,
        lim=min(limit, 20),
    )
    for row in authored:
        out.append(
            {
                "slice": "structural",
                "kind": "authored_by",
                "subject": row["commit_key"],
                "object": row["person_key"],
                "person_name": row.get("person_name"),
                "message": (row.get("message") or "")[:120],
                "gold_source_keys": [row["commit_key"], row["person_key"]],
                "gold_entity_keys": [row["commit_key"], row["person_key"]],
                "forbidden_keys": [],
                "must_refuse": False,
            }
        )
    return out


def mine_unanswerable(
    timeline: dict[str, dict],
    boundary: int,
    limit: int,
) -> list[dict]:
    out: list[dict] = []
    for nk, ev in timeline.items():
        if len(out) >= limit:
            break
        idx = ev.get("timeline_index")
        if idx is None or idx <= boundary:
            continue
        title = ev.get("title") or ev.get("message") or nk
        out.append(
            {
                "slice": "unanswerable",
                "kind": "out_of_corpus",
                "natural_key": nk,
                "timeline_index": idx,
                "title": (title or "")[:160],
                "event_type": ev.get("type"),
                "gold_source_keys": [],
                "gold_entity_keys": [],
                "forbidden_keys": [],
                "must_refuse": True,
                "hint_topic": (title or "")[:80],
            }
        )

    # Unrelated-repo fixtures (never in this graph)
    unrelated = [
        {
            "slice": "unanswerable",
            "kind": "unrelated_repo",
            "natural_key": "pr:999999",
            "title": "Why did Kubernetes adopt etcd for cluster state?",
            "gold_source_keys": [],
            "gold_entity_keys": [],
            "forbidden_keys": [],
            "must_refuse": True,
            "hint_topic": "Kubernetes etcd cluster state",
        },
        {
            "slice": "unanswerable",
            "kind": "unrelated_repo",
            "natural_key": "issue:888888",
            "title": "What is the default Redis eviction policy in AWS ElastiCache?",
            "gold_source_keys": [],
            "gold_entity_keys": [],
            "forbidden_keys": [],
            "must_refuse": True,
            "hint_topic": "AWS ElastiCache Redis eviction",
        },
        {
            "slice": "unanswerable",
            "kind": "unrelated_repo",
            "natural_key": "decision:nonexistent",
            "title": "When did React switch its default to concurrent rendering in Next.js App Router?",
            "gold_source_keys": [],
            "gold_entity_keys": [],
            "forbidden_keys": [],
            "must_refuse": True,
            "hint_topic": "Next.js App Router concurrent rendering",
        },
    ]
    out.extend(unrelated)
    return out


def mine_span(
    fact_candidates: Iterable[dict],
    timeline: dict[str, dict],
) -> list[dict]:
    results = []
    for cand in fact_candidates:
        src = cand.get("evidence_source") or ""
        excerpt = cand.get("excerpt") or ""
        ev = timeline.get(src)
        source_text = _artifact_text(ev) if ev else ""
        ok = _span_ok(excerpt, source_text)
        results.append(
            {
                "slice": "span",
                "decision_key": cand.get("decision_key"),
                "evidence_source": src,
                "excerpt_len": len(excerpt),
                "source_found": ev is not None,
                "span_aligned": ok,
            }
        )
    return results


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "evals" / "candidates.jsonl")
    parser.add_argument(
        "--span-out", type=Path, default=PROJECT_ROOT / "evals" / "span_alignment.json"
    )
    parser.add_argument("--fact-limit", type=int, default=80)
    parser.add_argument("--current-limit", type=int, default=50)
    parser.add_argument("--structural-limit", type=int, default=30)
    parser.add_argument("--unanswerable-limit", type=int, default=30)
    parser.add_argument(
        "--boundary",
        type=int,
        default=None,
        help="timeline_index boundary (default: process checkpoint)",
    )
    args = parser.parse_args()

    boundary = args.boundary
    if boundary is None:
        if config.PROCESS_CHECKPOINT_PATH.exists():
            with open(config.PROCESS_CHECKPOINT_PATH) as f:
                boundary = int(json.load(f).get("last_processed_index", -1))
        else:
            boundary = -1

    logger.info("Loading timeline from %s", config.UNIFIED_TIMELINE_PATH)
    timeline = _load_timeline_index(config.UNIFIED_TIMELINE_PATH)
    logger.info("Timeline index: %d events; boundary=%d", len(timeline), boundary)

    db = Neo4jClient(
        config.NEO4J_URI,
        config.NEO4J_USERNAME,
        config.NEO4J_PASSWORD,
        config.NEO4J_DATABASE,
    )
    try:
        fact = mine_fact(db, args.fact_limit)
        current = mine_current(db, args.current_limit)
        structural = mine_structural(db, timeline, args.structural_limit)
        unanswerable = mine_unanswerable(timeline, boundary, args.unanswerable_limit)
        span = mine_span(fact, timeline)
    finally:
        db.close()

    all_rows = fact + current + structural + unanswerable
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    aligned = sum(1 for s in span if s["span_aligned"])
    span_report = {
        "n": len(span),
        "aligned": aligned,
        "alignment_rate": round(aligned / len(span), 4) if span else 0.0,
        "source_missing": sum(1 for s in span if not s["source_found"]),
        "items": span,
    }
    with args.span_out.open("w") as f:
        json.dump(span_report, f, indent=2)

    counts = {
        "fact": len(fact),
        "current": len(current),
        "structural": len(structural),
        "unanswerable": len(unanswerable),
        "total": len(all_rows),
        "span_alignment_rate": span_report["alignment_rate"],
    }
    logger.info("Wrote %s (%s)", args.out, counts)
    logger.info("Wrote %s (alignment_rate=%.3f)", args.span_out, span_report["alignment_rate"])
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
