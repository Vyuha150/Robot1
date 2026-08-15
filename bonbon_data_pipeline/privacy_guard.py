"""Dataset-ingestion-time privacy policy: rules 3 and 4 from the brief.

  3. Do not store raw face/audio/video by default.
  4. Consent is required for face recognition enrollment.

Distinct from bonbon_field_learning.anonymized_event_store (which enforces
privacy on the RUNTIME field-failure event log, structurally -- no raw-media
field exists on AnonymizedEvent at all) and bonbon_data_feedback.core.
privacy_safe_data_policy.PrivacySafeDataPolicy (same enforcement for the
robot's own live ROS2 failure capture). This module enforces the equivalent
contract one layer up, at DATASET intake time: is a given dataset (which may
legitimately BE a corpus of raw face/audio/video, e.g. Common Voice audio or
a staff face-enrollment set) allowed to be stored raw, and was face
enrollment actually consented to.

`face_enrollment_requires_consent` is not a config toggle -- it is a fixed
property of this class, not read from privacy_policy.yaml, so a
misconfigured YAML can never silently disable it (same "structural, not by
convention" reasoning as anonymized_event_store's fixed absence of raw-media
fields).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from bonbon_data_pipeline.dataset_registry import DatasetEntry

MediaType = Literal["face", "audio", "video"]

_RAW_MEDIA_PRIVACY_RISKS: dict[str, MediaType] = {
    "contains_raw_face_images": "face",
    "contains_raw_audio": "audio",
    "contains_raw_video": "video",
}


@dataclass(frozen=True)
class ConsentRecord:
    subject_id: str  # e.g. staff badge ID -- never a patient ID (rule: staff enrollment only)
    consented_by: str
    consented_at: float
    scope: tuple[str, ...]  # e.g. ("face_recognition_enrollment",)
    revoked: bool = False


class ConsentRequiredError(PermissionError):
    """Raised when a face-recognition enrollment is attempted without a
    valid, unrevoked, in-scope ConsentRecord. Never caught-and-ignored by
    this module -- callers must obtain real consent, not work around it."""


@dataclass
class PrivacyPolicy:
    raw_face_storage_enabled: bool = False
    raw_audio_storage_enabled: bool = False
    raw_video_storage_enabled: bool = False
    retention_days: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "PrivacyPolicy":
        p = Path(path)
        if not p.exists():
            # Fail closed: no policy file means the strictest defaults
            # apply (everything above is already False), not "anything goes".
            return cls()
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls(
            raw_face_storage_enabled=bool(raw.get("raw_face_storage_enabled", False)),
            raw_audio_storage_enabled=bool(raw.get("raw_audio_storage_enabled", False)),
            raw_video_storage_enabled=bool(raw.get("raw_video_storage_enabled", False)),
            retention_days=dict(raw.get("retention_days", {})),
        )

    def raw_storage_enabled(self, media_type: MediaType) -> bool:
        return {
            "face": self.raw_face_storage_enabled,
            "audio": self.raw_audio_storage_enabled,
            "video": self.raw_video_storage_enabled,
        }[media_type]


class PrivacyGuard:
    def __init__(self, policy: PrivacyPolicy | None = None) -> None:
        self._policy = policy or PrivacyPolicy()

    # ── Rule 3: raw storage off by default ──────────────────────────────

    def check_dataset(self, entry: DatasetEntry) -> tuple[bool, str]:
        """Whether `entry` may be ingested as-is. A dataset whose
        privacy_risk names a raw-media category is only allowed when this
        guard's policy has that media type's raw storage explicitly
        enabled -- otherwise it must be preprocessed (embeddings only,
        landmarks only, transcripts only) before it can enter the pipeline,
        per `entry.preprocessing_needed`."""
        media_type = _RAW_MEDIA_PRIVACY_RISKS.get(entry.privacy_risk)
        if media_type is None:
            return True, f"privacy_risk={entry.privacy_risk!r} carries no raw-media storage concern"
        if self._policy.raw_storage_enabled(media_type):
            return True, f"raw {media_type} storage is explicitly enabled by policy for this deployment"
        return False, (
            f"dataset carries raw {media_type} data and raw {media_type} storage is disabled by default "
            f"(rule 3) -- must be preprocessed first: {entry.preprocessing_needed or 'no preprocessing plan on file'}"
        )

    # ── Rule 4: consent required for face enrollment ────────────────────

    face_enrollment_requires_consent: bool = True  # fixed, not configurable -- see module docstring

    def enroll_face(self, subject_id: str, consent: ConsentRecord | None) -> ConsentRecord:
        """The only way this module allows a face-recognition enrollment
        record to be created. Raises ConsentRequiredError, does not return
        False, so a caller cannot accidentally proceed past a rejection by
        forgetting to check a boolean."""
        if consent is None:
            raise ConsentRequiredError(
                f"face-recognition enrollment for {subject_id!r} requires a ConsentRecord; none provided"
            )
        if consent.subject_id != subject_id:
            raise ConsentRequiredError(
                f"consent record is for {consent.subject_id!r}, not the enrollment subject {subject_id!r}"
            )
        if consent.revoked:
            raise ConsentRequiredError(f"consent for {subject_id!r} has been revoked")
        if "face_recognition_enrollment" not in consent.scope:
            raise ConsentRequiredError(
                f"consent for {subject_id!r} does not cover scope 'face_recognition_enrollment' "
                f"(has: {consent.scope})"
            )
        return consent

    @staticmethod
    def new_consent(subject_id: str, consented_by: str, scope: tuple[str, ...]) -> ConsentRecord:
        return ConsentRecord(
            subject_id=subject_id, consented_by=consented_by, consented_at=time.time(), scope=scope
        )
