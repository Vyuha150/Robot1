"""Dedicated tests for bonbon_field_learning.HumanReviewQueue -- the queue
bonbon_operator_api's POST /data/failure-cases/review submits into.
"""

from __future__ import annotations

import pytest

from bonbon_field_learning import HumanReviewQueue, ReviewStatus


@pytest.fixture
def queue(tmp_path):
    return HumanReviewQueue(tmp_path / "review_queue.jsonl")


class TestHumanReviewQueue:
    def test_new_item_starts_pending(self, queue):
        item = queue.enqueue("event-1")
        assert item.status == ReviewStatus.PENDING

    def test_enqueue_is_idempotent(self, queue):
        first = queue.enqueue("event-1")
        second = queue.enqueue("event-1")
        assert first.event_id == second.event_id
        assert len(queue.pending()) == 1

    def test_approve_moves_item_out_of_pending(self, queue):
        queue.enqueue("event-1")
        queue.submit_review("event-1", reviewer="r1", approve=True)
        assert queue.pending() == []
        assert [i.event_id for i in queue.approved()] == ["event-1"]

    def test_reject_moves_item_out_of_pending_but_not_into_approved(self, queue):
        queue.enqueue("event-1")
        queue.submit_review("event-1", reviewer="r1", approve=False, notes="not a real bug")
        assert queue.pending() == []
        assert queue.approved() == []

    def test_review_without_prior_enqueue_still_creates_the_item(self, queue):
        item = queue.submit_review("event-2", reviewer="r1", approve=True)
        assert item.status == ReviewStatus.APPROVED

    def test_state_persists_across_instances(self, tmp_path):
        path = tmp_path / "review_queue.jsonl"
        HumanReviewQueue(path).submit_review("event-1", reviewer="r1", approve=True, notes="ok")
        reloaded = HumanReviewQueue(path)
        assert [i.event_id for i in reloaded.approved()] == ["event-1"]

    def test_reviewer_and_corrected_outcome_are_recorded(self, queue):
        item = queue.submit_review(
            "event-1", reviewer="staff_042", approve=True,
            corrected_expected_outcome={"expected_gesture": "stop_palm"},
        )
        assert item.reviewer == "staff_042"
        assert item.corrected_expected_outcome == {"expected_gesture": "stop_palm"}
        assert item.reviewed_at is not None
