"""Fail-closed write validation for the claim-graph agent."""
from __future__ import annotations

import pytest

from layerten.process.tools.validator import (
    ValidationError,
    validate_confidence,
    validate_evidence,
    validate_label,
    validate_predicate,
    validate_read_only_cypher,
)


def test_validate_evidence_requires_dict():
    with pytest.raises(ValidationError, match="required"):
        validate_evidence(None)
    with pytest.raises(ValidationError, match="required"):
        validate_evidence({})


def test_validate_evidence_requires_excerpt():
    with pytest.raises(ValidationError, match="excerpt"):
        validate_evidence({"source": "pr:1"})
    with pytest.raises(ValidationError, match="excerpt"):
        validate_evidence({"excerpt": ""})
    validate_evidence({"excerpt": "We switched to private buckets."})


def test_validate_confidence_rejects_below_threshold():
    with pytest.raises(ValidationError, match="0.4"):
        validate_confidence(0.3)
    with pytest.raises(ValidationError, match="0.0-1.0"):
        validate_confidence(1.5)
    validate_confidence(None)
    validate_confidence(0.4)
    validate_confidence(0.95)


def test_validate_label_rejects_unknown():
    with pytest.raises(ValidationError, match="not in allowed"):
        validate_label("Widget")
    validate_label("DesignDecision")


def test_validate_predicate_rejects_unknown():
    with pytest.raises(ValidationError, match="not in allowed"):
        validate_predicate("LIKES")
    validate_predicate("SUPERSEDES")


def test_validate_read_only_cypher_blocks_writes():
    validate_read_only_cypher("MATCH (n) RETURN n LIMIT 5")
    with pytest.raises(ValidationError, match="write keywords"):
        validate_read_only_cypher("MATCH (n) DELETE n")
    with pytest.raises(ValidationError, match="write keywords"):
        validate_read_only_cypher("MERGE (n:Person {natural_key: 'x'}) RETURN n")
    with pytest.raises(ValidationError, match="write keywords"):
        validate_read_only_cypher("MATCH (n) SET n.x = 1 RETURN n")
