"""
bonbon_vision.config.vision_config
====================================
Fully typed, nested configuration for the vision pipeline.

No model path is hardcoded — all paths come from ROS2 parameters
(via the launch file or param YAML).  This module only defines the
*shape* of the config and provides safe defaults.

Usage
-----
    from bonbon_vision.config import VisionConfig
    cfg = VisionConfig.from_ros_params(node)   # preferred — reads ROS2 params
    cfg = VisionConfig.from_dict(d)             # from a plain dict
    cfg = VisionConfig.from_yaml(path)          # from a YAML file
    d   = cfg.to_dict()                         # serialise for logging / storage
"""

from __future__ import annotations

import copy
import logging
from dataclasses import asdict, dataclass, field, fields
from typing import Any

logger = logging.getLogger(__name__)


# ── Sub-configs ───────────────────────────────────────────────────────────────


@dataclass
class DetectorConfig:
    """YOLO / fallback object-detector settings."""

    # Backend: "yolo" | "hog" | "mock" | "degraded"
    backend: str = "mock"

    # Path to YOLO weights file — MUST be set when backend="yolo"
    # Not hardcoded: inject at deploy time via ROS2 parameter.
    model_path: str = ""

    # Detection confidence and NMS thresholds
    confidence_threshold: float = 0.45
    nms_iou_threshold: float = 0.45

    # Compute device: "" = auto-select, "cpu", "cuda:0", "mps"
    device: str = ""

    # Input long-side resolution fed to YOLO (multiple of 32)
    img_size: int = 640

    # COCO class IDs to keep; empty list = all classes
    classes: list[int] = field(default_factory=list)

    # Per-inference wall-clock timeout (seconds); 0 = disabled
    inference_timeout_sec: float = 1.0

    # Consecutive timeouts before entering degraded mode
    max_consecutive_timeouts: int = 3

    # Use FP16 inference (requires CUDA or Metal)
    half_precision: bool = False

    def validate(self) -> None:
        if self.backend == "yolo" and not self.model_path:
            raise ValueError(
                "DetectorConfig.model_path must be set when backend='yolo'. "
                "Pass it as a ROS2 parameter: detector_model_path:=/path/to/model.pt"
            )
        if not 0.0 < self.confidence_threshold <= 1.0:
            raise ValueError(
                f"confidence_threshold must be in (0, 1], got {self.confidence_threshold}"
            )
        if self.img_size % 32 != 0:
            raise ValueError(f"img_size must be a multiple of 32, got {self.img_size}")


@dataclass
class FaceConfig:
    """Face detection and recognition settings."""

    # Detection backend: "opencv_dnn" | "insightface" | "mock"
    detect_backend: str = "mock"

    # Recognition backend: "deepface" | "insightface" | "mock"
    recognize_backend: str = "mock"

    # Path to face embedding database (SQLite for deepface, directory for insightface)
    # NOT hardcoded — inject via ROS2 parameter face_db_path
    db_path: str = ""

    # Cosine distance threshold: smaller = stricter matching
    recognition_threshold: float = 0.40

    # OpenCV DNN prototxt + weights (used when detect_backend="opencv_dnn")
    dnn_prototxt_path: str = ""
    dnn_weights_path: str = ""

    # Maximum face detection inference wall-clock time
    inference_timeout_sec: float = 0.5

    # Minimum face detection confidence
    min_face_confidence: float = 0.70

    # Age group estimation (requires additional model)
    enable_age_estimation: bool = False

    # Body-pose gaze estimation to set PersonState.facing_robot
    enable_gaze_estimation: bool = False

    def validate(self) -> None:
        if self.recognize_backend != "mock" and not self.db_path:
            logger.warning(
                "FaceConfig.db_path is empty — recognition will always return ''. "
                "Set face_db_path ROS2 parameter to enable identity matching."
            )


@dataclass
class PreprocessConfig:
    """OpenCV image preprocessing pipeline settings."""

    # Target resolution fed into the detector (before YOLO internal resize)
    resize_width: int = 640
    resize_height: int = 480

    # CLAHE (Contrast Limited Adaptive Histogram Equalisation)
    # Applied automatically when mean brightness < brightness_threshold
    enable_clahe: bool = True
    clahe_clip_limit: float = 2.0
    clahe_tile_grid_size: int = 8  # tile grid: NxN

    # Gaussian blur for noise suppression (applied before detection)
    enable_denoise: bool = False
    denoise_kernel_size: int = 3  # must be odd

    # Mean brightness (0–255) below which frame is considered "low-light"
    brightness_threshold: float = 50.0

    # Frame quality gates — frames failing these checks are skipped
    min_mean_brightness: float = 2.0  # below this = black / camera off
    max_nan_fraction: float = 0.50  # depth frames with > 50% NaN → depth unused

    def validate(self) -> None:
        if self.denoise_kernel_size % 2 == 0:
            raise ValueError(f"denoise_kernel_size must be odd, got {self.denoise_kernel_size}")


@dataclass
class PrivacyConfig:
    """
    Privacy-safe mode settings.

    When enabled:
      - All detected face regions are blurred in any published images.
      - PersonState.face_id is suppressed (always "").
      - Optional: disable annotated image publishing entirely.
    """

    # Master switch — set True in patient-facing deployments
    enabled: bool = False

    # Blur face ROIs in annotated image
    blur_faces: bool = True

    # Gaussian blur kernel size for face blurring (must be odd, ≥ 3)
    blur_kernel_size: int = 51

    # Pixelate instead of Gaussian blur (stronger anonymisation)
    pixelate_faces: bool = False
    pixelate_block_size: int = 16

    # Suppress face_id in PersonStateArray even when recognised
    suppress_identity: bool = True

    # When True the annotated image topic is never published
    disable_annotated_publish: bool = False

    def validate(self) -> None:
        if self.blur_kernel_size % 2 == 0 or self.blur_kernel_size < 3:
            raise ValueError(f"blur_kernel_size must be odd and ≥ 3, got {self.blur_kernel_size}")


@dataclass
class TrackingConfig:
    """Multi-object tracker settings."""

    # IoU threshold for greedy assignment
    iou_threshold: float = 0.30

    # Frames before a LOST track is deleted
    max_lost_frames: int = 15

    # Maximum simultaneous tracks (safety cap)
    max_tracks: int = 20

    # Minimum consecutive hits before a track is CONFIRMED (published)
    min_hits_to_confirm: int = 2


# ── Top-level config ──────────────────────────────────────────────────────────


@dataclass
class VisionConfig:
    """
    Complete, typed configuration for the BonBon vision pipeline.

    Construct via one of the factory methods; do NOT instantiate directly
    unless all nested configs are fully specified.
    """

    detector: DetectorConfig = field(default_factory=DetectorConfig)
    face: FaceConfig = field(default_factory=FaceConfig)
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)

    # Node-level settings
    detection_rate_hz: float = 10.0
    health_rate_hz: float = 1.0
    hfov_deg: float = 60.0

    # Publish a BGR-annotated image for debugging (high bandwidth)
    publish_annotated_image: bool = False

    # Annotated image compression: "raw" | "jpeg" | "png"
    annotated_encoding: str = "bgr8"

    # If True, node enters graceful degraded mode instead of crashing
    # when the model fails to load
    allow_degraded_startup: bool = True

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VisionConfig:
        """Build from a plain Python dict (e.g., loaded from YAML)."""
        d = copy.deepcopy(d)
        cfg = cls()
        cfg.detector = _fill(DetectorConfig, d.pop("detector", {}))
        cfg.face = _fill(FaceConfig, d.pop("face", {}))
        cfg.preprocess = _fill(PreprocessConfig, d.pop("preprocess", {}))
        cfg.privacy = _fill(PrivacyConfig, d.pop("privacy", {}))
        cfg.tracking = _fill(TrackingConfig, d.pop("tracking", {}))
        for k, v in d.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    @classmethod
    def from_yaml(cls, path: str) -> VisionConfig:
        """Load from a YAML file."""
        import yaml

        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_ros_params(cls, node) -> VisionConfig:
        """
        Read all vision parameters from a rclpy Node's declared parameters.

        The node must have declared the parameters beforehand (done in
        VisionNode._declare_parameters).
        """

        def _p(name: str, default=None):
            try:
                return node.get_parameter(name).value
            except Exception:
                return default

        cfg = cls()
        # Detector
        cfg.detector.backend = _p("detector_backend", "mock")
        cfg.detector.model_path = _p("detector_model_path", "")
        cfg.detector.confidence_threshold = _p("detector_confidence", 0.45)
        cfg.detector.nms_iou_threshold = _p("detector_nms_iou", 0.45)
        cfg.detector.device = _p("detector_device", "")
        cfg.detector.img_size = int(_p("detector_img_size", 640))
        cfg.detector.inference_timeout_sec = _p("detector_timeout_sec", 1.0)
        cfg.detector.max_consecutive_timeouts = int(_p("detector_max_timeouts", 3))
        cfg.detector.half_precision = bool(_p("detector_half", False))

        # Face
        cfg.face.detect_backend = _p("face_detect_backend", "mock")
        cfg.face.recognize_backend = _p("face_recognize_backend", "mock")
        cfg.face.db_path = _p("face_db_path", "")
        cfg.face.recognition_threshold = _p("face_recognition_threshold", 0.40)
        cfg.face.dnn_prototxt_path = _p("face_dnn_prototxt_path", "")
        cfg.face.dnn_weights_path = _p("face_dnn_weights_path", "")
        cfg.face.inference_timeout_sec = _p("face_timeout_sec", 0.5)
        cfg.face.min_face_confidence = _p("face_min_confidence", 0.70)

        # Preprocess
        cfg.preprocess.resize_width = int(_p("preprocess_width", 640))
        cfg.preprocess.resize_height = int(_p("preprocess_height", 480))
        cfg.preprocess.enable_clahe = bool(_p("preprocess_clahe", True))
        cfg.preprocess.clahe_clip_limit = _p("preprocess_clahe_clip", 2.0)
        cfg.preprocess.enable_denoise = bool(_p("preprocess_denoise", False))
        cfg.preprocess.brightness_threshold = _p("preprocess_brightness_threshold", 50.0)

        # Privacy
        cfg.privacy.enabled = bool(_p("privacy_enabled", False))
        cfg.privacy.blur_faces = bool(_p("privacy_blur_faces", True))
        cfg.privacy.blur_kernel_size = int(_p("privacy_blur_kernel", 51))
        cfg.privacy.pixelate_faces = bool(_p("privacy_pixelate", False))
        cfg.privacy.suppress_identity = bool(_p("privacy_suppress_id", True))
        cfg.privacy.disable_annotated_publish = bool(_p("privacy_disable_annotated", False))

        # Tracking
        cfg.tracking.iou_threshold = _p("tracking_iou_threshold", 0.30)
        cfg.tracking.max_lost_frames = int(_p("tracking_max_lost", 15))
        cfg.tracking.max_tracks = int(_p("tracking_max_tracks", 20))

        # Top-level
        cfg.detection_rate_hz = _p("detection_rate_hz", 10.0)
        cfg.health_rate_hz = _p("health_rate_hz", 1.0)
        cfg.hfov_deg = _p("hfov_deg", 60.0)
        cfg.publish_annotated_image = bool(_p("publish_annotated", False))
        cfg.allow_degraded_startup = bool(_p("allow_degraded", True))

        return cfg

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> None:
        """Raise ValueError for any invalid combination of settings."""
        self.detector.validate()
        self.face.validate()
        self.preprocess.validate()
        self.privacy.validate()
        if self.detection_rate_hz <= 0:
            raise ValueError(f"detection_rate_hz must be > 0, got {self.detection_rate_hz}")
        if not 10.0 <= self.hfov_deg <= 180.0:
            raise ValueError(f"hfov_deg must be in [10, 180], got {self.hfov_deg}")

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """One-line human-readable config summary for structured logging."""
        return (
            f"detector={self.detector.backend!r} "
            f"model={self.detector.model_path!r} "
            f"face_detect={self.face.detect_backend!r} "
            f"face_recog={self.face.recognize_backend!r} "
            f"privacy={self.privacy.enabled} "
            f"rate={self.detection_rate_hz}Hz "
            f"clahe={self.preprocess.enable_clahe} "
            f"annotated={self.publish_annotated_image}"
        )


# ── Helper ────────────────────────────────────────────────────────────────────


def _fill(cls, d: dict[str, Any]):
    """Fill a dataclass from a dict, ignoring unknown keys."""
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in valid})
