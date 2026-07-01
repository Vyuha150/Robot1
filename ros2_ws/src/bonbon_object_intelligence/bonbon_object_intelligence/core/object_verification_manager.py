"""ObjectVerificationManager — the second check before an ALIAS-strategy
class label (see object_class_registry.py) is ever reported.

Honest scope: there is no CLIP/SigLIP model wired into this repo today
(same "no fitted calibration dataset" honesty as confidence_calibrator.py).
`verifier_fn` is a pluggable hook for exactly that -- a callable taking
(target_class_name, base_class_name, bbox) and returning a confidence
0.0-1.0 -- so a real vision-language verifier can be dropped in later
without changing this class's contract. Without one configured, the
manager falls back to two justifiable, dataset-free rules:

  1. Persistence: the same track must be seen as the base class for
     `min_consecutive_frames` before an alias label is trusted at all --
     a single frame is never enough to relabel "person" as "child".
  2. Geometry, for the one alias where a cheap geometric signal exists:
     "child" (person + a bounding-box-height ratio well below what an
     adult occupies at the same depth/position in frame).

Every other ALIAS class relies on rule 1 alone -- explicitly weaker
evidence, reflected in a lower `confidence` on the VerificationResult
rather than a false claim of certainty.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bonbon_object_intelligence.core.object_class_registry import ClassSpec, ObjectClassRegistry

VerifierFn = Callable[[str, str, tuple[int, int, int, int]], float]


@dataclass
class VerificationConfig:
    min_consecutive_frames: int = 3
    # Bbox height / frame height below this ratio is a "child" candidate
    # (a rough, honestly-labeled heuristic, not a fitted model).
    child_max_bbox_height_ratio: float = 0.55
    persistence_only_confidence: float = 0.5
    geometry_confirmed_confidence: float = 0.75
    verifier_fn: VerifierFn | None = None


@dataclass(frozen=True)
class VerificationResult:
    confirmed: bool
    reported_class: str
    confidence: float
    evidence_frames: int
    reason: str


class ObjectVerificationManager:
    def __init__(
        self, registry: ObjectClassRegistry, config: VerificationConfig | None = None
    ) -> None:
        self._registry = registry
        self._cfg = config or VerificationConfig()
        # (track_id, target_class_name) -> consecutive-frame count
        self._streaks: dict[tuple[str, str], int] = {}

    def reset_track(self, track_id: str) -> None:
        """Called when a track is lost/re-identified so old evidence never
        silently carries into a different physical object."""
        for key in [k for k in self._streaks if k[0] == track_id]:
            del self._streaks[key]

    def verify(
        self,
        track_id: str,
        base_class: str,
        bbox: tuple[int, int, int, int],
        frame_height: float,
    ) -> list[VerificationResult]:
        """Returns a VerificationResult per ALIAS class this base_class
        could honestly become, confirmed or not. An empty list means no
        ALIAS strategy applies to this base_class at all."""
        candidates = [
            s
            for s in self._registry.candidates_for_base_class(base_class)
            if s.requires_verification
        ]
        results: list[VerificationResult] = []
        for spec in candidates:
            key = (track_id, spec.name)
            self._streaks[key] = self._streaks.get(key, 0) + 1
            streak = self._streaks[key]
            results.append(self._evaluate(spec, base_class, bbox, frame_height, streak))
        return results

    def _evaluate(
        self,
        spec: ClassSpec,
        base_class: str,
        bbox: tuple[int, int, int, int],
        frame_height: float,
        streak: int,
    ) -> VerificationResult:
        if self._cfg.verifier_fn is not None:
            score = self._cfg.verifier_fn(spec.name, base_class, bbox)
            confirmed = score >= 0.5 and streak >= self._cfg.min_consecutive_frames
            return VerificationResult(
                confirmed,
                spec.name if confirmed else base_class,
                score,
                streak,
                "pluggable_verifier",
            )

        if streak < self._cfg.min_consecutive_frames:
            return VerificationResult(
                False,
                base_class,
                0.0,
                streak,
                f"only {streak}/{self._cfg.min_consecutive_frames} consecutive frames",
            )

        if spec.name == "child" and frame_height > 0:
            _, _, _, h = bbox
            ratio = h / frame_height
            if ratio <= self._cfg.child_max_bbox_height_ratio:
                return VerificationResult(
                    True,
                    "child",
                    self._cfg.geometry_confirmed_confidence,
                    streak,
                    f"persisted {streak} frames + bbox_height_ratio={ratio:.2f}",
                )
            return VerificationResult(
                False, base_class, 0.0, streak, f"bbox_height_ratio={ratio:.2f} too tall for child"
            )

        # Persistence-only alias (no geometric signal available): confirmed,
        # but at a deliberately lower confidence than a geometry-backed one.
        return VerificationResult(
            True,
            spec.name,
            self._cfg.persistence_only_confidence,
            streak,
            f"persisted {streak} frames (persistence-only, no geometric signal)",
        )
