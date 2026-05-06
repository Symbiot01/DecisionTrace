"""Repo scoping for the raw event log.

Regression cover for the defect that fused two repositories into one graph:
event IDs like ``pr:1`` are only unique within a repo, so an unscoped dedup set
made a fetch for repo B skip repo B's PRs because repo A had already written
``pr:1``. The result was a graph with Plane commits and SQLModel pull requests
and ~1,600 fabricated cross-repo edges.
"""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Reload the store module against a temp event log and a fixed repo."""

    def _load(repo: str):
        from layerten import config

        monkeypatch.setattr(config, "TARGET_REPO", repo, raising=False)
        monkeypatch.setattr(config, "RAW_EVENTS_PATH", tmp_path / "events.jsonl")
        monkeypatch.setattr(config, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

        import layerten.store.raw_events as raw_events

        importlib.reload(raw_events)
        return raw_events

    return _load


def test_write_stamps_repo(store):
    mod = store("tiangolo/sqlmodel")
    mod.write_raw_event("pr", "1", {"title": "first"})

    line = json.loads(mod.RAW_EVENTS_PATH.read_text().strip())
    assert line["repo"] == "tiangolo/sqlmodel"
    assert line["id"] == "pr:1"


def test_fetched_ids_are_scoped_by_repo(store):
    mod = store("tiangolo/sqlmodel")
    mod.write_raw_event("pr", "1", {"title": "sqlmodel pr 1"})
    assert mod.get_fetched_ids("pr") == {"pr:1"}

    # A different repo must not see the first repo's PR as already fetched,
    # otherwise its own PR #1 is silently skipped.
    other = store("makeplane/plane")
    assert other.get_fetched_ids("pr") == set()


def test_unstamped_legacy_events_do_not_mask_a_fetch(store):
    mod = store("tiangolo/sqlmodel")
    mod.RAW_EVENTS_PATH.write_text(
        json.dumps({"id": "pr:1", "event_type": "pr", "payload": {}}) + "\n"
    )
    assert mod.get_fetched_ids("pr") == set()


def test_assert_single_repo_rejects_a_mixed_log(store):
    mod = store("tiangolo/sqlmodel")
    mod.write_raw_event("pr", "1", {"title": "sqlmodel"})

    other = store("makeplane/plane")
    other.write_raw_event("commit", "abc123", {"message": "plane"})

    with pytest.raises(other.RepoMismatchError, match="fuse repositories"):
        other.assert_single_repo()


def test_assert_single_repo_accepts_a_clean_log(store):
    mod = store("tiangolo/sqlmodel")
    mod.write_raw_event("pr", "1", {"title": "sqlmodel"})
    mod.write_raw_event("commit", "abc123", {"message": "sqlmodel"})

    mod.assert_single_repo()
    assert mod.scan_repos() == {"tiangolo/sqlmodel": 2}
