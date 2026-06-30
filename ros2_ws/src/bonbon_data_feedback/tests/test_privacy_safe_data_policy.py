"""Tests for PrivacySafeDataPolicy — the hard "no raw biometrics by default" gate."""

from __future__ import annotations

from bonbon_data_feedback.core.privacy_safe_data_policy import PrivacySafeDataPolicy


class TestRawSnapshotGating:
    def test_raw_snapshot_disallowed_by_default(self):
        policy = PrivacySafeDataPolicy()
        assert policy.is_raw_snapshot_allowed() is False

    def test_raw_snapshot_allowed_only_when_explicitly_enabled(self):
        policy = PrivacySafeDataPolicy(debug_mode_enabled=True)
        assert policy.is_raw_snapshot_allowed() is True

    def test_default_constructor_never_implicitly_enables_debug(self):
        policy = PrivacySafeDataPolicy()
        assert policy.debug_mode_enabled is False


class TestContextSanitization:
    def test_safe_context_passes_through_unchanged(self):
        policy = PrivacySafeDataPolicy()
        result = policy.sanitize_context({"category": "gesture", "confidence": 0.4})
        assert result.sanitized == {"category": "gesture", "confidence": 0.4}
        assert result.stripped_keys == []

    def test_forbidden_keys_stripped_even_outside_debug_mode(self):
        policy = PrivacySafeDataPolicy()
        result = policy.sanitize_context({"category": "face", "face_embedding": [0.1, 0.2]})
        assert "face_embedding" not in result.sanitized
        assert "face_embedding" in result.stripped_keys

    def test_forbidden_keys_stripped_EVEN_in_debug_mode(self):
        """Debug mode controls raw_snapshot_path, never raw payload riding
        along in the general context dict — this must never change."""
        policy = PrivacySafeDataPolicy(debug_mode_enabled=True)
        result = policy.sanitize_context({"audio_bytes": b"\x00\x01", "category": "speaker"})
        assert "audio_bytes" not in result.sanitized
        assert "audio_bytes" in result.stripped_keys

    def test_case_insensitive_key_matching(self):
        policy = PrivacySafeDataPolicy()
        result = policy.sanitize_context({"Face_Image": "data"})
        assert "Face_Image" not in result.sanitized

    def test_multiple_forbidden_keys_all_stripped(self):
        policy = PrivacySafeDataPolicy()
        result = policy.sanitize_context(
            {"face_embedding": [], "audio_bytes": b"", "category": "object"}
        )
        assert result.sanitized == {"category": "object"}
        assert set(result.stripped_keys) == {"face_embedding", "audio_bytes"}


class TestRetention:
    def test_face_has_shortest_default_retention(self):
        policy = PrivacySafeDataPolicy()
        assert policy.retention_days_for("face") < policy.retention_days_for("object")

    def test_unknown_category_uses_default_retention(self):
        policy = PrivacySafeDataPolicy()
        assert policy.retention_days_for("unknown_category") == policy.retention_days_for("default")

    def test_custom_retention_overrides_default(self):
        policy = PrivacySafeDataPolicy(retention_days_by_category={"face": 7})
        assert policy.retention_days_for("face") == 7

    def test_is_expired_true_past_retention_window(self):
        policy = PrivacySafeDataPolicy(retention_days_by_category={"object": 1})
        now = 1_000_000.0
        created_at = now - (2 * 86400.0)  # 2 days ago, retention is 1 day
        assert policy.is_expired("object", created_at, now) is True

    def test_is_expired_false_within_retention_window(self):
        policy = PrivacySafeDataPolicy(retention_days_by_category={"object": 10})
        now = 1_000_000.0
        created_at = now - 86400.0  # 1 day ago, retention is 10 days
        assert policy.is_expired("object", created_at, now) is False
