"""Required test 3: raw face/audio/video storage disabled by default.
Required test 4: consent required for face-recognition enrollment.
"""

from __future__ import annotations

import time

import pytest

from bonbon_data_pipeline.dataset_registry import DatasetEntry
from bonbon_data_pipeline.privacy_guard import (
    ConsentRecord,
    ConsentRequiredError,
    PrivacyGuard,
    PrivacyPolicy,
)


def _raw_face_entry() -> DatasetEntry:
    return DatasetEntry(
        dataset_id="faces", name="Faces", source_url="internal", capability="face_recognition",
        domain="staff", license="internal", commercial_allowed="true",
        privacy_risk="contains_raw_face_images", download_allowed=False, intended_use="",
        prohibited_use="", preprocessing_needed="", target_model="", evaluation_metric="",
        edge_export_format="onnx", status="NEEDS_REVIEW",
    )


class TestRequiredBehavior3RawStorageDisabledByDefault:
    def test_default_policy_has_all_raw_storage_disabled(self):
        policy = PrivacyPolicy()
        assert policy.raw_face_storage_enabled is False
        assert policy.raw_audio_storage_enabled is False
        assert policy.raw_video_storage_enabled is False

    def test_missing_policy_file_fails_closed(self, tmp_path):
        policy = PrivacyPolicy.load(tmp_path / "does_not_exist.yaml")
        assert policy.raw_face_storage_enabled is False

    def test_raw_face_dataset_blocked_by_default(self):
        guard = PrivacyGuard()
        allowed, reason = guard.check_dataset(_raw_face_entry())
        assert allowed is False
        assert "disabled by default" in reason

    def test_raw_face_dataset_allowed_once_policy_explicitly_enables_it(self):
        guard = PrivacyGuard(PrivacyPolicy(raw_face_storage_enabled=True))
        allowed, _ = guard.check_dataset(_raw_face_entry())
        assert allowed is True

    def test_non_raw_media_dataset_is_unaffected_by_policy(self):
        entry = DatasetEntry(
            dataset_id="synth", name="Synthetic", source_url="internal", capability="object_detection",
            domain="x", license="internal", commercial_allowed="true", privacy_risk="none",
            download_allowed=True, intended_use="", prohibited_use="", preprocessing_needed="",
            target_model="", evaluation_metric="", edge_export_format="onnx", status="APPROVED",
        )
        guard = PrivacyGuard()  # strictest default policy
        allowed, _ = guard.check_dataset(entry)
        assert allowed is True


class TestRequiredBehavior4ConsentRequiredForFaceEnrollment:
    def test_enrollment_without_consent_raises(self):
        guard = PrivacyGuard()
        with pytest.raises(ConsentRequiredError):
            guard.enroll_face("staff_001", consent=None)

    def test_enrollment_with_valid_consent_succeeds(self):
        guard = PrivacyGuard()
        consent = PrivacyGuard.new_consent("staff_001", "hr_admin", scope=("face_recognition_enrollment",))
        result = guard.enroll_face("staff_001", consent)
        assert result is consent

    def test_enrollment_with_revoked_consent_raises(self):
        guard = PrivacyGuard()
        consent = ConsentRecord(
            subject_id="staff_001", consented_by="hr_admin", consented_at=time.time(),
            scope=("face_recognition_enrollment",), revoked=True,
        )
        with pytest.raises(ConsentRequiredError, match="revoked"):
            guard.enroll_face("staff_001", consent)

    def test_enrollment_with_wrong_scope_raises(self):
        guard = PrivacyGuard()
        consent = PrivacyGuard.new_consent("staff_001", "hr_admin", scope=("dashboard_access",))
        with pytest.raises(ConsentRequiredError, match="scope"):
            guard.enroll_face("staff_001", consent)

    def test_enrollment_with_mismatched_subject_raises(self):
        guard = PrivacyGuard()
        consent = PrivacyGuard.new_consent("staff_002", "hr_admin", scope=("face_recognition_enrollment",))
        with pytest.raises(ConsentRequiredError):
            guard.enroll_face("staff_001", consent)

    def test_consent_requirement_is_not_configurable(self):
        # face_enrollment_requires_consent is a fixed class attribute, not
        # read from any policy file -- this asserts it structurally.
        assert PrivacyGuard.face_enrollment_requires_consent is True
