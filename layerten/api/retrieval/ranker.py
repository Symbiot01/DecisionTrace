from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


def rank_results(
    candidates: list[dict[str, Any]],
    expanded: dict[str, dict[str, Any]],
    keywords: list[str],
    limit: int = 10,
    min_confidence: float = 0.4,
    intent: str = "general",
) -> list[dict[str, Any]]:
    """Score and rank candidates. Returns top results with their expanded data."""
    scored: list[tuple[float, dict]] = []
    now = datetime.now(timezone.utc)
    why_style = intent == "decision" or (keywords and any(k in ("why", "reason", "rationale") for k in keywords))

    for cand in candidates:
        nk = cand["props"].get("natural_key", "")
        expansion = expanded.get(nk, {"claims": [], "linked_entities": []})
        claims = expansion.get("claims", [])

        conf_claims = [c for c in claims
                       if c.get("confidence") is not None
                       and (c.get("confidence") or 0) >= min_confidence]
        evidence_claims = [c for c in conf_claims if c.get("evidence_excerpt")]

        node_evidence = cand["props"].get("evidence_excerpt")

        text_blob = " ".join(filter(None, [
            str(cand["props"].get("title", "")),
            str(cand["props"].get("body", "")),
            str(cand["props"].get("message", "")),
            str(node_evidence or ""),
        ])).lower()

        for key in ("description", "rationale", "summary"):
            v = cand["props"].get(key)
            if v:
                text_blob += " " + str(v).lower()

        for c in evidence_claims:
            text_blob += " " + str(c.get("evidence_excerpt", "")).lower()

        kw_hits = sum(1 for kw in keywords if kw.lower() in text_blob) if keywords else 1
        kw_score = kw_hits / max(len(keywords), 1)

        max_conf = max(
            (c.get("confidence") or 0 for c in conf_claims),
            default=cand.get("ft_score", 0.5),
        )

        event_time_str = cand["props"].get("event_time_from") or cand["props"].get("created_at")
        recency = _recency_decay(event_time_str, now)

        direct_bonus = 1.5 if cand.get("source") == "direct" else 1.0
        ft_bonus = 1.0 + min(cand.get("ft_score", 0) / 10.0, 0.5)

        rationale_bonus = 1.0
        if why_style and cand.get("label") == "DesignDecision":
            if cand["props"].get("description") or cand["props"].get("rationale"):
                rationale_bonus = 1.4

        score = kw_score * max_conf * recency * direct_bonus * ft_bonus * rationale_bonus

        best_claims = evidence_claims if evidence_claims else conf_claims[:5]

        scored.append((score, {
            "natural_key": nk,
            "label": cand["label"],
            "props": cand["props"],
            "claims": best_claims,
            "linked_entities": expansion.get("linked_entities", []),
            "score": round(score, 4),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def _recency_decay(time_val: Any, now: datetime, half_life_days: float = 365.0) -> float:
    """Exponential decay: score=1.0 for recent, 0.5 after half_life_days."""
    if time_val is None:
        return 0.5
    try:
        if hasattr(time_val, "to_native"):
            dt = time_val.to_native()
        elif isinstance(time_val, str):
            clean = re.sub(r"\[.*\]$", "", time_val)
            dt = datetime.fromisoformat(clean)
        elif isinstance(time_val, datetime):
            dt = time_val
        else:
            return 0.5
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (now - dt).total_seconds() / 86400
        return math.exp(-0.693 * age_days / half_life_days)
    except Exception:
        return 0.5
