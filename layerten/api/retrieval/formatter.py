from __future__ import annotations

from typing import Any

from layerten import config
from layerten.process.neo4j_client import Neo4jClient

GITHUB_BASE = f"https://github.com/{config.TARGET_REPO}"


def github_url(natural_key: str) -> str | None:
    """Reconstruct a GitHub URL from a natural key."""
    if not natural_key:
        return None
    parts = natural_key.split(":", 1)
    if len(parts) != 2:
        return None
    prefix, ident = parts
    urls = {
        "pr": f"{GITHUB_BASE}/pull/{ident}",
        "issue": f"{GITHUB_BASE}/issues/{ident}",
        "commit": f"{GITHUB_BASE}/commit/{ident}",
        "discussion": f"{GITHUB_BASE}/discussions/{ident}",
        "tag": f"{GITHUB_BASE}/releases/tag/{ident}",
        "file": f"{GITHUB_BASE}/blob/main/{ident}",
        "person": f"https://github.com/{ident}",
    }
    return urls.get(prefix)


def _to_str(val: Any) -> str | None:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def format_result(rank: int, item: dict) -> dict:
    """Format a single ranked result into the API response shape."""
    nk = item["natural_key"]
    props = item["props"]
    claims = item.get("claims", [])

    best_claim = claims[0] if claims else None
    supersedes_info = None
    for c in claims:
        if c.get("predicate") == "SUPERSEDES":
            supersedes_info = {
                "natural_key": c.get("object_key"),
                "evidence_excerpt": c.get("evidence_excerpt"),
            }
            break

    evidence = None
    if best_claim:
        evidence = _format_evidence(best_claim, props)
    if not evidence or not evidence.get("excerpt"):
        node_excerpt = props.get("evidence_excerpt")
        node_source = props.get("evidence_source") or nk
        if node_excerpt:
            evidence = {
                "excerpt": node_excerpt,
                "source_key": node_source,
                "source_url": github_url(node_source),
                "timestamp": _to_str(props.get("created_at")),
            }

    subject_entity: dict = {
        "type": item["label"],
        "natural_key": nk,
        "title": props.get("title") or props.get("display_name") or props.get("message", "")[:80],
        "url": github_url(nk),
    }
    if props.get("description"):
        subject_entity["description"] = props["description"]
    if props.get("rationale"):
        subject_entity["rationale"] = props["rationale"]
    if props.get("summary"):
        subject_entity["summary"] = props["summary"]

    result = {
        "rank": rank,
        "score": item["score"],
        "claim": _format_claim(best_claim) if best_claim else None,
        "subject_entity": subject_entity,
        "evidence": evidence,
        "linked_entities": [
            {
                "natural_key": le["natural_key"],
                "type": le["type"],
                "display_name": le.get("display_name", le["natural_key"]),
            }
            for le in item.get("linked_entities", [])[:10]
        ],
        "supersedes": supersedes_info,
    }
    return result


def _format_claim(claim: dict) -> dict:
    return {
        "subject_key": claim.get("subject_key"),
        "predicate": claim.get("predicate"),
        "object_key": claim.get("object_key"),
        "confidence": claim.get("confidence"),
        "event_time": _to_str(claim.get("event_time")),
    }


def _format_evidence(claim: dict, props: dict) -> dict:
    source_key = claim.get("evidence_source") or ""
    return {
        "excerpt": claim.get("evidence_excerpt"),
        "source_key": source_key,
        "source_url": github_url(source_key),
        "timestamp": _to_str(claim.get("event_time")),
    }


def format_context_pack(
    question: str,
    intent: str,
    ranked: list[dict],
    total_candidates: int,
    processing_ms: int,
    db: Neo4jClient,
) -> dict:
    """Build the full context pack response."""
    results = [format_result(i + 1, item) for i, item in enumerate(ranked)]

    conflicts = _detect_conflicts(ranked)

    return {
        "question": question,
        "intent": intent,
        "results": results,
        "conflicts": conflicts,
        "metadata": {
            "candidates_found": total_candidates,
            "returned": len(results),
            "processing_ms": processing_ms,
        },
    }


def _detect_conflicts(ranked: list[dict]) -> list[dict]:
    """Find claims where the same (subject, predicate) has different objects."""
    seen: dict[tuple, list] = {}
    for item in ranked:
        for claim in item.get("claims", []):
            key = (claim.get("subject_key"), claim.get("predicate"))
            if key[0] and key[1]:
                seen.setdefault(key, []).append(claim)

    conflicts = []
    for key, claims in seen.items():
        objects = set(c.get("object_key") for c in claims if c.get("object_key"))
        if len(objects) > 1:
            conflicts.append({
                "subject_key": key[0],
                "predicate": key[1],
                "conflicting_objects": list(objects),
                "claims": claims,
            })
    return conflicts
