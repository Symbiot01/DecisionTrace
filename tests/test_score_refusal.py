"""Scoring semantics for refusals and invented citations.

The original scorer treated any citation as disqualifying a refusal, and counted
a citation to a real retrieved source as an invented source id. That scored the
system's best unanswerable behaviour -- denying the fact while pointing at the
near miss -- as two separate failures.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

from score import _cited_keys, _is_refusal  # noqa: E402


def test_marker_outside_source_list_is_invented():
    cited, invented = _cited_keys("see [7]", [{"evidence": {"source_key": "pr:1"}}])
    assert cited == []
    assert invented == [7]


def test_marker_inside_source_list_resolves_to_its_key():
    cited, invented = _cited_keys("see [1]", [{"evidence": {"source_key": "pr:1"}}])
    assert cited == ["pr:1"]
    assert invented == []


def test_source_without_key_counts_as_invented():
    cited, invented = _cited_keys("see [1]", [{"evidence": {}}])
    assert cited == []
    assert invented == [1]


def test_denial_citing_the_near_miss_is_a_refusal():
    """Grounded refusal: denies the fact, cites what the evidence does cover."""
    answer = (
        "There is no mention of a built-in query result cache. The evidence "
        "covers SQL compilation caching [1]."
    )
    assert _is_refusal(answer, ["pr:1"]) is True


def test_assertive_answer_with_a_citation_is_not_a_refusal():
    """The leniency must not extend to actually answering an unanswerable
    question -- that is the failure the refusal metric exists to catch."""
    assert _is_refusal("SQLModel caches query results in Redis [1].", ["pr:1"]) is False


def test_answer_with_no_citations_at_all_is_a_refusal():
    assert _is_refusal("I could not find anything relevant.", []) is True
