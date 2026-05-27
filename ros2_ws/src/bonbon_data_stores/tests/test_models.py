"""Test scenarios 2-4: Pydantic domain models — construction, validation, privacy."""

from __future__ import annotations

import pytest
from bonbon_data_stores.schema.models import (
    BaseEvent,
    InteractionEvent,
    MapMetadata,
    PrivacyLevel,
    RAGSearchResult,
    RetentionPolicy,
    RobotState,
    SafetyEvent,
    SafetyEventType,
    UserRecord,
    VectorSearchResult,
)

# ---------------------------------------------------------------------------
# Test scenario 2: Privacy level enforcement
# ---------------------------------------------------------------------------


class TestPrivacyLevelEnum:
    def test_all_values_present(self):
        levels = {lvl.value for lvl in PrivacyLevel}
        assert "public" in levels
        assert "internal" in levels
        assert "sensitive" in levels
        assert "restricted" in levels
        assert "do_not_store" in levels

    def test_do_not_store_is_storable_false(self):
        event = BaseEvent(privacy_level=PrivacyLevel.DO_NOT_STORE)
        assert event.is_storable() is False

    def test_all_other_levels_are_storable(self):
        for level in PrivacyLevel:
            if level != PrivacyLevel.DO_NOT_STORE:
                event = BaseEvent(privacy_level=level)
                assert event.is_storable() is True

    def test_coercion_from_string(self):
        event = BaseEvent(privacy_level="sensitive")
        assert event.privacy_level == PrivacyLevel.SENSITIVE

    def test_invalid_privacy_level_raises(self):
        with pytest.raises(Exception):
            BaseEvent(privacy_level="top_secret")


# ---------------------------------------------------------------------------
# Test scenario 3: Retention policy defaults
# ---------------------------------------------------------------------------


class TestRetentionPolicy:
    def test_all_policies_present(self):
        policies = {p.value for p in RetentionPolicy}
        assert "ephemeral" in policies
        assert "7_days" in policies
        assert "30_days" in policies
        assert "1_year" in policies
        assert "permanent_until_deleted" in policies

    def test_default_retention_for_interactions(self):
        event = InteractionEvent(input_text="hi")
        assert event.retention_policy == RetentionPolicy.THIRTY_DAYS

    def test_default_retention_for_safety_events(self):
        event = SafetyEvent(event_type=SafetyEventType.COLLISION_RISK)
        assert event.retention_policy == RetentionPolicy.ONE_YEAR

    def test_default_retention_for_robot_states(self):
        state = RobotState()
        assert state.retention_policy == RetentionPolicy.SEVEN_DAYS


# ---------------------------------------------------------------------------
# Test scenario 4: Domain model construction and defaults
# ---------------------------------------------------------------------------


class TestUserRecord:
    def test_constructs_with_display_name(self):
        u = UserRecord(display_name="Bob")
        assert u.display_name == "Bob"
        assert u.language == "en"
        assert u.is_anonymous is False
        assert u.user_id  # auto-generated

    def test_face_encoding_ref_default_none(self):
        """Biometric data should never be populated by default."""
        u = UserRecord(display_name="Carol")
        assert u.face_encoding_ref is None

    def test_preferences_default_empty(self):
        u = UserRecord(display_name="Dave")
        assert u.preferences == []


class TestInteractionEvent:
    def test_auto_fields(self):
        e = InteractionEvent()
        assert e.event_id
        assert e.timestamp > 0
        assert e.audio_ref is None  # raw audio never stored by default

    def test_audio_ref_default_none(self):
        """Raw audio must never be stored unless explicitly set."""
        e = InteractionEvent(input_text="test")
        assert e.audio_ref is None


class TestSafetyEvent:
    def test_severity_bounds(self):
        with pytest.raises(Exception):
            SafetyEvent(event_type=SafetyEventType.COLLISION_RISK, severity=0)
        with pytest.raises(Exception):
            SafetyEvent(event_type=SafetyEventType.COLLISION_RISK, severity=6)

    def test_resolved_default_false(self):
        e = SafetyEvent(event_type=SafetyEventType.EMERGENCY_STOP)
        assert e.resolved is False
        assert e.resolved_at is None


class TestMapMetadata:
    def test_defaults(self):
        m = MapMetadata(map_name="floor_1")
        assert m.is_active is False
        assert m.zones == []


class TestVectorSearchResult:
    def test_constructs(self):
        r = VectorSearchResult(vector_id="v1", score=0.92)
        assert r.vector_id == "v1"
        assert r.score == pytest.approx(0.92)


class TestRAGSearchResult:
    def test_constructs(self):
        r = RAGSearchResult(doc_id="d1", collection="knowledge", score=0.8, document="Hello")
        assert r.collection == "knowledge"
