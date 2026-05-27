"""bonbon_perception_ai.fusion — multimodal sensor fusion layer."""

from bonbon_perception_ai.fusion.modality_buffer import ModalityBuffer
from bonbon_perception_ai.fusion.multimodal_fusion import MultimodalFusion
from bonbon_perception_ai.fusion.stale_detector import StaleDetector
from bonbon_perception_ai.fusion.types import (
    FusionContext,
    NavStatus,
    ObjectObservation,
    PersonObservation,
    RobotPose,
    SpeechInput,
)

__all__ = [
    "FusionContext",
    "ObjectObservation",
    "PersonObservation",
    "SpeechInput",
    "RobotPose",
    "NavStatus",
    "ModalityBuffer",
    "StaleDetector",
    "MultimodalFusion",
]
