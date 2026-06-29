"""Tests for InMemoryObjectMemoryHook."""

from __future__ import annotations

from bonbon_object_intelligence.core.object_memory_hook import (
    InMemoryObjectMemoryHook,
    ObjectMemoryEntry,
)


def _entry(track_id="obj_1", class_name="chair", t=0.0):
    return ObjectMemoryEntry(track_id, class_name, 1.0, 2.0, 0.0, t)


class TestRememberRecall:
    def test_recall_unknown_returns_none(self):
        hook = InMemoryObjectMemoryHook()
        assert hook.recall("obj_x") is None

    def test_remember_then_recall(self):
        hook = InMemoryObjectMemoryHook()
        hook.remember(_entry("obj_1"))
        result = hook.recall("obj_1")
        assert result is not None
        assert result.class_name == "chair"

    def test_remember_overwrites_same_id(self):
        hook = InMemoryObjectMemoryHook()
        hook.remember(_entry("obj_1", t=0.0))
        hook.remember(_entry("obj_1", t=5.0))
        assert hook.recall("obj_1").last_seen_at == 5.0


class TestRecallByClass:
    def test_finds_all_matching_class(self):
        hook = InMemoryObjectMemoryHook()
        hook.remember(_entry("obj_1", "chair"))
        hook.remember(_entry("obj_2", "chair"))
        hook.remember(_entry("obj_3", "bag"))
        result = hook.recall_by_class("chair")
        assert len(result) == 2

    def test_no_matches_returns_empty(self):
        hook = InMemoryObjectMemoryHook()
        assert hook.recall_by_class("chair") == []


class TestBoundedCapacity:
    def test_evicts_oldest_when_full(self):
        hook = InMemoryObjectMemoryHook(max_entries=2)
        hook.remember(_entry("obj_1", t=0.0))
        hook.remember(_entry("obj_2", t=1.0))
        hook.remember(_entry("obj_3", t=2.0))
        assert hook.recall("obj_1") is None  # oldest evicted
        assert hook.recall("obj_3") is not None
