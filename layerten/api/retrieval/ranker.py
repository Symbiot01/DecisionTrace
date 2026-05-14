from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


# Absolute floor; the relative floor below does most of the filtering.
MIN_SCORE_FLOOR = 0.02
# Drop candidates scoring below this fraction of the top hit, so a strong match
# suppresses lexical noise while a weak field keeps its best few candidates.
REL_SCORE_FLOOR = 0.15
# History-style intents may still surface superseded decisions.
_HISTORY_INTENTS = frozenset({"history", "what_changed"})
# Text length (chars) beyond which long bodies start losing keyword-match credit.
_LENGTH_PIVOT = 2000.0
# Lexical credit given to a node purely for adjoining an entity the question named.
_ANCHOR_AFFINITY = 0.6


def _text_blob(props: dict[str, Any], evidence_claims: list[dict]) -> str:
    parts = [
        props.get("title"),
        props.get("body"),
        props.get("message"),
        props.get("evidence_excerpt"),
        props.get("description"),
        props.get("rationale"),
        props.get("summary"),
    ]
    blob = " ".join(str(p) for p in parts if p)
    for c in evidence_claims:
        excerpt = c.get("evidence_excerpt")
        if excerpt:
            blob += " " + str(excerpt)
    return blob.lower()


def _idf_weights(keywords: list[str], blobs: list[str]) -> dict[str, float]:
    """Local IDF over the candidate pool.

    Terms present in nearly every candidate (usually the words that drove recall)
    carry little ranking signal; rare terms are what actually discriminate.
    """
    n = max(len(blobs), 1)
    weights: dict[str, float] = {}
    for kw in keywords:
        k = kw.lower()
        if k in weights:
            continue
        df = sum(1 for b in blobs if k in b)
        weights[k] = math.log(1.0 + n / (1.0 + df))
    return weights


def rank_results(
    candidates: list[dict[str, Any]],
    expanded: dict[str, dict[str, Any]],
    keywords: list[str],
    limit: int = 10,
    min_confidence: float = 0.4,
    intent: str = "general",
    min_score: float = MIN_SCORE_FLOOR,
    rel_floor: float = REL_SCORE_FLOOR,
) -> list[dict[str, Any]]:
    """Score and rank candidates. Returns top results with their expanded data."""
    now = datetime.now(timezone.utc)
    why_style = intent in ("decision", "why") or (
        keywords and any(k in ("why", "reason", "rationale") for k in keywords)
    )
    allow_superseded = intent in _HISTORY_INTENTS

    # Pass 1: materialise per-candidate text so IDF and fulltext scores can be
    # normalised across the pool rather than against arbitrary constants.
    prepared: list[dict[str, Any]] = []
    for cand in candidates:
        props = cand["props"]
        nk = props.get("natural_key", "")

        # Query-time supersession: hide non-current decisions for non-history intents.
        if (
            not allow_superseded
            and cand.get("label") == "DesignDecision"
            and props.get("is_current") is False
        ):
            continue

        expansion = expanded.get(nk, {"claims": [], "linked_entities": []})
        claims = expansion.get("claims", [])
        conf_claims = [
            c
            for c in claims
            if c.get("confidence") is not None
            and (c.get("confidence") or 0) >= min_confidence
        ]
        evidence_claims = [c for c in conf_claims if c.get("evidence_excerpt")]

        prepared.append(
            {
                "cand": cand,
                "props": props,
                "nk": nk,
                "expansion": expansion,
                "conf_claims": conf_claims,
                "evidence_claims": evidence_claims,
                "blob": _text_blob(props, evidence_claims),
            }
        )

    if not prepared:
        return []

    idf = _idf_weights(keywords, [p["blob"] for p in prepared])
    idf_total = sum(idf.values()) or 1.0
    max_ft = max((p["cand"].get("ft_score", 0.0) or 0.0) for p in prepared) or 1.0

    scored: list[tuple[float, dict]] = []
    for p in prepared:
        cand, props, blob = p["cand"], p["props"], p["blob"]
        conf_claims, evidence_claims = p["conf_claims"], p["evidence_claims"]

        # IDF-weighted keyword coverage: matching a rare term beats matching many
        # common ones. Long bodies are damped so big commit messages stop winning
        # on incidental term overlap alone.
        if keywords:
            matched = sum(w for k, w in idf.items() if k in blob)
            kw_score = matched / idf_total
            length_factor = math.sqrt(_LENGTH_PIVOT / max(_LENGTH_PIVOT, len(blob)))
            kw_score *= length_factor
        else:
            kw_score = 1.0

        # kw_score multiplies the whole product, so zero lexical overlap means zero
        # relevance. That is wrong for relational questions: the PR that closed a
        # named issue shares no vocabulary with "which pull request closed issue
        # #64" -- the edge to the anchor is the evidence. Being adjacent to an
        # entity the question named substitutes for lexical overlap here.
        if cand.get("source") == "anchor_hop":
            kw_score = max(kw_score, _ANCHOR_AFFINITY)

        # Claim confidence is a probability. It must never be filled with a raw
        # Lucene score, which is unbounded and would promote evidence-free nodes.
        if conf_claims:
            evidence_conf = max((c.get("confidence") or 0.0) for c in conf_claims)
        else:
            evidence_conf = 0.5
        evidence_conf = min(1.0, max(0.0, float(evidence_conf)))

        event_time_str = props.get("event_time_from") or props.get("created_at")
        recency = _recency_decay(event_time_str, now)

        # An entity the question names by key is the anchor of the question, not
        # a keyword guess. Its own text often matches the question poorly ("issue
        # #64" says nothing about "pull request closed"), so a multiplicative
        # nudge cannot save it from full-text noise -- it is pinned below instead.
        source = cand.get("source")
        direct_bonus = 1.6 if source == "anchor_hop" else 1.0
        ft_bonus = 1.0 + 0.5 * ((cand.get("ft_score", 0.0) or 0.0) / max_ft)

        rationale_bonus = 1.0
        if why_style and cand.get("label") == "DesignDecision":
            if props.get("description") or props.get("rationale"):
                rationale_bonus = 1.4
            else:
                rationale_bonus = 1.15

        # This pipeline exists to produce citable answers, so nodes carrying an
        # actual excerpt outrank nodes that could only be cited by key.
        has_evidence = bool(props.get("evidence_excerpt")) or bool(evidence_claims)
        evidence_bonus = 1.25 if has_evidence else 0.85

        current_penalty = 0.25 if props.get("is_current") is False else 1.0

        score = (
            kw_score
            * evidence_conf
            * recency
            * direct_bonus
            * ft_bonus
            * rationale_bonus
            * evidence_bonus
            * current_penalty
        )

        best_claims = evidence_claims if evidence_claims else conf_claims[:5]
        scored.append(
            (
                1 if source == "direct" else 0,
                score,
                {
                    "natural_key": p["nk"],
                    "label": cand["label"],
                    "props": props,
                    "claims": best_claims,
                    "linked_entities": p["expansion"].get("linked_entities", []),
                    "score": round(score, 4),
                },
            )
        )

    # Entities named outright in the question rank above everything the search
    # merely guessed at, and are exempt from the relevance cutoff: if the user
    # said "issue #64", issue:64 belongs in the answer whatever its text score.
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if not scored:
        return []

    top = max(s for _, s, _ in scored)
    cutoff = max(min_score, top * rel_floor)
    return [item for pin, s, item in scored[:limit] if pin or s >= cutoff]


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
        # A timestamp meaningfully in the future is bad data, not fresh data.
        # Clamping it to age 0 would hand it the maximum recency score, so treat
        # it as unknown instead. A day of tolerance absorbs clock skew.
        if age_days < -1.0:
            return 0.5
        age_days = max(0.0, age_days)
        return math.exp(-0.693 * age_days / half_life_days)
    except Exception:
        return 0.5
