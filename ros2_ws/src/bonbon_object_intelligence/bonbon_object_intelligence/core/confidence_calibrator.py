"""ObjectConfidenceCalibrator — class-specific confidence adjustment + small-
object floor, and duplicate-detection rejection.

Honest scope note: there is no labeled calibration dataset anywhere in this
repo, so this is NOT a fitted statistical calibration model (no Platt
scaling / isotonic regression — that would require validation data this
project doesn't have). What it IS: a configurable adjustment hook operators
can tune once real calibration data exists (YOLO-family detectors are
well-documented to be systematically overconfident on some classes), plus
two real, justifiable rules that don't need any dataset:
  - small objects (small bbox area) get a LOWER confidence floor rather than
    being rejected outright, since detector confidence is inherently lower
    for small objects regardless of whether the detection is correct.
  - near-duplicate detections of the same class at nearly the same position
    (a known YOLO failure mode — overlapping anchor boxes both firing) are
    collapsed to the single highest-confidence one.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CalibratorConfig:
    class_confidence_adjustment: dict[str, float] = field(default_factory=dict)
    small_object_area_px: float = 900.0  # e.g. 30x30 px
    small_object_confidence_floor: float = 0.35
    rejection_threshold: float = 0.3
    duplicate_iou_threshold: float = 0.6


@dataclass
class CalibratedDetection:
    class_name: str
    raw_confidence: float
    calibrated_confidence: float
    is_small_object: bool
    rejected: bool


def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class ObjectConfidenceCalibrator:
    def __init__(self, config: CalibratorConfig | None = None) -> None:
        self._cfg = config or CalibratorConfig()

    def calibrate(
        self, class_name: str, confidence: float, bbox: tuple[int, int, int, int]
    ) -> CalibratedDetection:
        adjustment = self._cfg.class_confidence_adjustment.get(class_name, 1.0)
        adjusted = max(0.0, min(1.0, confidence * adjustment))

        area = bbox[2] * bbox[3]
        is_small = 0 < area < self._cfg.small_object_area_px
        if is_small and adjusted < self._cfg.small_object_confidence_floor:
            # Small objects are never rejected purely for being small —
            # detector confidence is inherently lower at small scale
            # regardless of detection correctness.
            adjusted = self._cfg.small_object_confidence_floor

        rejected = adjusted < self._cfg.rejection_threshold
        return CalibratedDetection(class_name, confidence, adjusted, is_small, rejected)

    def deduplicate(
        self, detections: list[tuple[str, float, tuple[int, int, int, int]]]
    ) -> list[tuple[str, float, tuple[int, int, int, int]]]:
        """Collapses near-duplicate same-class detections to the highest-confidence one."""
        kept: list[tuple[str, float, tuple[int, int, int, int]]] = []
        for class_name, confidence, bbox in sorted(detections, key=lambda d: -d[1]):
            is_dup = any(
                k_class == class_name
                and _bbox_iou(k_bbox, bbox) >= self._cfg.duplicate_iou_threshold
                for k_class, _, k_bbox in kept
            )
            if not is_dup:
                kept.append((class_name, confidence, bbox))
        return kept
