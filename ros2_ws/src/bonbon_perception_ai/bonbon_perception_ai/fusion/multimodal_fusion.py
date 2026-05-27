"""
bonbon_perception_ai.fusion.multimodal_fusion
==============================================
Combines all incoming modalities into a single FusionContext snapshot.

Thread model
------------
* update_*() methods are called from ROS2 subscription callbacks (any thread).
* fuse() is called from the perception timer callback (single thread).
* ModalityBuffer handles per-field locking.
"""

from __future__ import annotations

import time

from bonbon_perception_ai.config.perception_config import FusionConfig
from bonbon_perception_ai.fusion.modality_buffer import ModalityBuffer
from bonbon_perception_ai.fusion.stale_detector import StaleDetector
from bonbon_perception_ai.fusion.types import (
    FusionContext,
    NavStatus,
    ObjectObservation,
    PersonObservation,
    RobotPose,
    SpeechInput,
)


class MultimodalFusion:
    """
    Manages one ModalityBuffer per input channel.

    All update_*() calls are non-blocking.
    fuse() returns a consistent, immutable FusionContext snapshot.
    """

    MODALITY_NAMES = ("objects", "persons", "speech", "robot_pose", "nav_status")

    def __init__(self, cfg: FusionConfig) -> None:
        self.cfg = cfg
        self._buffers: dict[str, ModalityBuffer] = {
            "objects": ModalityBuffer("objects", cfg.objects_stale_sec),
            "persons": ModalityBuffer("persons", cfg.persons_stale_sec),
            "speech": ModalityBuffer("speech", cfg.speech_stale_sec),
            "robot_pose": ModalityBuffer("robot_pose", cfg.pose_stale_sec),
            "nav_status": ModalityBuffer("nav_status", cfg.nav_stale_sec),
        }
        self._stale_detector = StaleDetector()

    # ── Update methods (called by ROS2 callbacks) ─────────────────────────────

    def update_objects(self, objects: list[ObjectObservation]) -> None:
        filtered = [o for o in objects if o.confidence >= self.cfg.min_object_confidence]
        self._buffers["objects"].update(filtered)

    def update_persons(self, persons: list[PersonObservation]) -> None:
        filtered = [p for p in persons if p.confidence >= self.cfg.min_person_confidence]
        self._buffers["persons"].update(filtered)

    def update_speech(self, speech: SpeechInput) -> None:
        self._buffers["speech"].update(speech)

    def update_pose(self, pose: RobotPose) -> None:
        self._buffers["robot_pose"].update(pose)

    def update_nav_status(self, nav: NavStatus) -> None:
        self._buffers["nav_status"].update(nav)

    # ── Fuse (called by perception timer) ─────────────────────────────────────

    def fuse(self) -> FusionContext:
        """
        Snapshot all buffers atomically and return a FusionContext.

        Note: "atomically" here means each buffer is read under its own lock;
        we do not hold all locks simultaneously to avoid priority inversion.
        The resulting context is therefore a best-effort snapshot; millisecond
        clock skew between individual buffer reads is acceptable.
        """
        stale, uncertainty = self._stale_detector.assess(self._buffers)

        objects_raw, _ = self._buffers["objects"].get()
        persons_raw, _ = self._buffers["persons"].get()
        speech_raw, _ = self._buffers["speech"].get()
        pose_raw, _ = self._buffers["robot_pose"].get()
        nav_raw, _ = self._buffers["nav_status"].get()

        return FusionContext(
            timestamp=time.monotonic(),
            objects=list(objects_raw) if objects_raw is not None else [],
            persons=list(persons_raw) if persons_raw is not None else [],
            speech=speech_raw,
            robot_pose=pose_raw,
            nav_status=nav_raw,
            stale_modalities=stale,
            uncertainty_level=uncertainty,
        )

    # ── Housekeeping ──────────────────────────────────────────────────────────

    def clear_all(self) -> None:
        """Flush all buffers (called on deactivate / privacy wipe)."""
        for buf in self._buffers.values():
            buf.clear()

    def modality_ages(self) -> dict[str, float]:
        """Return age-in-seconds for each modality (for health reporting)."""
        return self._stale_detector.detail_report(self._buffers)

    def buffers(self) -> dict[str, ModalityBuffer]:
        return dict(self._buffers)
