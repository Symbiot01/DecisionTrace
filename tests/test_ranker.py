"""Ranking invariants.

These cover the scoring defects found while diagnosing low cite-precision:
an unbounded Lucene score being used in place of claim confidence, long bodies
winning on incidental keyword overlap, and superseded decisions surfacing for
current-state questions.
"""

from __future__ import annotations

from layerten.api.retrieval.ranker import rank_results


def cand(nk, label="DesignDecision", source="fulltext", ft=0.0, **props):
    return {
        "label": label,
        "source": source,
        "ft_score": ft,
        "props": {"natural_key": nk, **props},
    }


def expansion(**per_key):
    return {k: {"claims": v, "linked_entities": []} for k, v in per_key.items()}


def claim(conf, excerpt="an excerpt", predicate="DECISION_FOR"):
    return {
        "confidence": conf,
        "evidence_excerpt": excerpt,
        "evidence_source": "pr:1",
        "predicate": predicate,
    }


def test_fulltext_score_does_not_substitute_for_confidence():
    """A node with no confidence-bearing claims must not inherit a huge Lucene
    score as its confidence. It previously outranked a well-evidenced node."""
    candidates = [
        cand("decision:no-evidence", ft=19.5, title="cache invalidation policy"),
        cand("decision:well-evidenced", ft=1.0, title="cache invalidation policy"),
    ]
    exp = expansion(
        **{
            "decision:no-evidence": [],
            "decision:well-evidenced": [claim(0.9)],
        }
    )
    ranked = rank_results(candidates, exp, ["cache", "invalidation"], limit=5)
    assert ranked[0]["natural_key"] == "decision:well-evidenced"


def test_long_body_does_not_beat_a_focused_match():
    """Length damping: a huge commit message that happens to contain the terms
    should not outrank a short title that is actually about them."""
    filler = " ".join(f"unrelated{i}" for i in range(4000))
    candidates = [
        cand(
            "commit:huge",
            label="Commit",
            message=f"cache invalidation {filler}",
        ),
        cand("decision:focused", title="cache invalidation policy"),
    ]
    exp = expansion(
        **{"commit:huge": [claim(0.9)], "decision:focused": [claim(0.9)]}
    )
    ranked = rank_results(candidates, exp, ["cache", "invalidation"], limit=5)
    assert ranked[0]["natural_key"] == "decision:focused"


def test_rare_keyword_outweighs_a_common_one():
    """IDF: matching the term that discriminates should beat matching the term
    every candidate shares."""
    candidates = [
        cand("decision:common-only", title="database migration"),
        cand("decision:has-rare", title="database migration alembic"),
        cand("decision:filler-1", title="database migration"),
        cand("decision:filler-2", title="database migration"),
    ]
    exp = expansion(
        **{
            "decision:common-only": [claim(0.9)],
            "decision:has-rare": [claim(0.9)],
            "decision:filler-1": [claim(0.9)],
            "decision:filler-2": [claim(0.9)],
        }
    )
    ranked = rank_results(
        candidates, exp, ["database", "migration", "alembic"], limit=5
    )
    assert ranked[0]["natural_key"] == "decision:has-rare"


def test_superseded_decisions_are_hidden_for_current_intent():
    candidates = [
        cand("decision:old", title="use redis", is_current=False),
        cand("decision:new", title="use redis", is_current=True),
    ]
    exp = expansion(**{"decision:old": [claim(0.9)], "decision:new": [claim(0.9)]})
    ranked = rank_results(candidates, exp, ["redis"], limit=5, intent="current_state")
    keys = [r["natural_key"] for r in ranked]
    assert "decision:old" not in keys
    assert "decision:new" in keys


def test_superseded_decisions_survive_history_intent():
    candidates = [
        cand("decision:old", title="use redis", is_current=False),
        cand("decision:new", title="use redis", is_current=True),
    ]
    exp = expansion(**{"decision:old": [claim(0.9)], "decision:new": [claim(0.9)]})
    ranked = rank_results(candidates, exp, ["redis"], limit=5, intent="history")
    assert "decision:old" in [r["natural_key"] for r in ranked]


def test_relative_floor_drops_noise_but_keeps_the_best_hit():
    """A weak field should still return its best candidate rather than nothing,
    which is what an absolute floor did to hard questions."""
    candidates = [
        cand("decision:weak-best", title="obscure topic"),
        cand("decision:weaker", title="completely different words here"),
    ]
    exp = expansion(
        **{"decision:weak-best": [claim(0.5)], "decision:weaker": [claim(0.5)]}
    )
    ranked = rank_results(candidates, exp, ["obscure", "topic"], limit=5)
    assert ranked
    assert ranked[0]["natural_key"] == "decision:weak-best"


def test_evidence_bearing_node_outranks_an_evidence_free_one():
    candidates = [
        cand("decision:bare", title="retry policy"),
        cand("decision:cited", title="retry policy"),
    ]
    exp = expansion(
        **{"decision:bare": [], "decision:cited": [claim(0.5)]}
    )
    ranked = rank_results(candidates, exp, ["retry", "policy"], limit=5)
    assert ranked[0]["natural_key"] == "decision:cited"


def test_empty_candidates_returns_empty():
    assert rank_results([], {}, ["anything"]) == []


def test_future_timestamp_is_treated_as_unknown_not_freshest():
    """A far-future date is bad data. It must score as unknown rather than as
    the freshest possible node, and must not beat a genuinely fresh one."""
    from datetime import datetime, timedelta, timezone

    today = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    candidates = [
        cand("decision:future", title="topic", created_at="2099-01-01T00:00:00Z"),
        cand("decision:fresh", title="topic", created_at=today),
        cand("decision:undated", title="topic"),
    ]
    exp = expansion(
        **{
            "decision:future": [claim(0.9)],
            "decision:fresh": [claim(0.9)],
            "decision:undated": [claim(0.9)],
        }
    )
    ranked = rank_results(candidates, exp, ["topic"], limit=5)
    scores = {r["natural_key"]: r["score"] for r in ranked}
    assert scores["decision:future"] < scores["decision:fresh"]
    assert scores["decision:future"] == scores["decision:undated"]


def test_named_entity_outranks_stronger_lexical_match():
    """An entity the question names by key is the anchor of the question. Its own
    text may match the question poorly ("issue:64" says nothing about "pull
    request closed"), so it must be pinned above better-matching noise."""
    candidates = [
        cand("issue:64", label="Issue", source="direct", title="a bug report"),
        cand("pr:922", label="PullRequest", ft=9.0,
             title="Bump tiangolo/issue-manager, closes a pull request issue"),
    ]
    exp = expansion(**{"issue:64": [claim(0.9)], "pr:922": [claim(0.9)]})
    ranked = rank_results(
        candidates, exp, ["pull", "request", "closed", "issue"], limit=8
    )
    assert ranked[0]["natural_key"] == "issue:64"


def test_named_entity_survives_the_relevance_cutoff():
    """The anchor must not be dropped by the relative floor just because a noisy
    candidate scored far higher on keywords."""
    candidates = [
        cand("issue:64", label="Issue", source="direct", title="unrelated wording"),
        cand("pr:922", label="PullRequest", ft=9.0,
             title="pull request closed issue " * 5),
    ]
    exp = expansion(**{"issue:64": [claim(0.9)], "pr:922": [claim(0.9)]})
    ranked = rank_results(
        candidates, exp, ["pull", "request", "closed", "issue"], limit=8
    )
    assert "issue:64" in {r["natural_key"] for r in ranked}


def test_anchor_neighbour_is_not_zeroed_by_absent_keyword_overlap():
    """The PR that closed a named issue shares no vocabulary with the question.
    Adjacency to the anchor has to substitute for lexical overlap, otherwise the
    multiplicative keyword term drives its score to zero and it is cut."""
    candidates = [
        cand("pr:1830", label="PullRequest", source="anchor_hop",
             title="Add model_fields_optional to convert inherited fields"),
        cand("pr:2", label="PullRequest", ft=5.0, title="pull request closed issue"),
    ]
    exp = expansion(**{"pr:1830": [claim(0.9)], "pr:2": [claim(0.9)]})
    ranked = rank_results(
        candidates, exp, ["pull", "request", "closed", "issue"], limit=8
    )
    assert "pr:1830" in {r["natural_key"] for r in ranked}
