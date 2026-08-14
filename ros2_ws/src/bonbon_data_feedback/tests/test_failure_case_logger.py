"""Tests for FailureCaseLogger — entry point gated by PrivacySafeDataPolicy."""

from __future__ import annotations

from bonbon_data_feedback.core.failure_case_logger import FailureCaseLogger
from bonbon_data_feedback.core.feedback_store import FeedbackStore
from bonbon_data_feedback.core.privacy_safe_data_policy import PrivacySafeDataPolicy


def _logger(tmp_path, debug_mode=False):
    store = FeedbackStore(tmp_path / "feedback.db")
    policy = PrivacySafeDataPolicy(debug_mode_enabled=debug_mode)
    return FailureCaseLogger(store, policy), store


class TestBasicLogging:
    def test_log_returns_case_id(self, tmp_path):
        logger, _ = _logger(tmp_path)
        case_id = logger.log("gesture", "low_confidence", "point", 0.4)
        assert case_id

    def test_logged_case_is_queryable(self, tmp_path):
        logger, store = _logger(tmp_path)
        logger.log("object", "mismatch", "cup", 0.3, expected_label="bottle")
        cases = store.query_failure_cases(category="object")
        assert len(cases) == 1
        assert cases[0].expected_label == "bottle"


class TestSiteAndLanguageCode:
    def test_site_id_and_language_code_reach_the_stored_record(self, tmp_path):
        logger, store = _logger(tmp_path)
        case_id = logger.log(
            "speaker",
            "low_confidence",
            "unknown",
            0.3,
            site_id="hospital_pune_01",
            language_code="hi",
        )
        got = store.get_failure_case(case_id)
        assert got.site_id == "hospital_pune_01"
        assert got.language_code == "hi"

    def test_defaults_to_empty_when_not_supplied(self, tmp_path):
        logger, store = _logger(tmp_path)
        case_id = logger.log("gesture", "low_confidence", "wave", 0.4)
        got = store.get_failure_case(case_id)
        assert got.site_id == ""
        assert got.language_code == ""


class TestPrivacyGating:
    def test_context_forbidden_keys_stripped_before_storage(self, tmp_path):
        logger, store = _logger(tmp_path)
        case_id = logger.log(
            "face",
            "mismatch",
            "person_a",
            0.5,
            context={"face_embedding": [1, 2, 3], "frame_idx": 9},
        )
        got = store.get_failure_case(case_id)
        assert "face_embedding" not in got.context
        assert got.context["frame_idx"] == 9

    def test_raw_snapshot_dropped_outside_debug_mode(self, tmp_path):
        logger, store = _logger(tmp_path, debug_mode=False)
        case_id = logger.log(
            "face", "mismatch", "person_a", 0.5, raw_snapshot_path="/tmp/face_001.jpg"
        )
        got = store.get_failure_case(case_id)
        assert got.has_raw_snapshot is False
        assert got.raw_snapshot_path == ""

    def test_raw_snapshot_kept_only_in_explicit_debug_mode(self, tmp_path):
        logger, store = _logger(tmp_path, debug_mode=True)
        case_id = logger.log(
            "face", "mismatch", "person_a", 0.5, raw_snapshot_path="/tmp/face_001.jpg"
        )
        got = store.get_failure_case(case_id)
        assert got.has_raw_snapshot is True
        assert got.raw_snapshot_path == "/tmp/face_001.jpg"

    def test_no_raw_snapshot_path_means_no_snapshot_even_in_debug_mode(self, tmp_path):
        logger, store = _logger(tmp_path, debug_mode=True)
        case_id = logger.log("gesture", "low_confidence", "wave", 0.4)
        got = store.get_failure_case(case_id)
        assert got.has_raw_snapshot is False
