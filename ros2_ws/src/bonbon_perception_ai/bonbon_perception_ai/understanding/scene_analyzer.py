"""
bonbon_perception_ai.understanding.scene_analyzer
==================================================
Converts a FusionContext into a SceneSnapshot and emits ContextEvents
whenever the scene changes meaningfully.

Design
------
* Pure Python — no ROS2 imports.
* Stateful: holds the previous snapshot to diff against.
* Deterministic: same inputs → same outputs.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from bonbon_perception_ai.config.perception_config import SceneConfig
from bonbon_perception_ai.fusion.types import FusionContext

# ── Output types ──────────────────────────────────────────────────────────────


@dataclass
class ContextEvent:
    event_type: str
    subject_id: str
    confidence: float
    description: str
    prior_value: str = ""
    new_value: str = ""
    related_ids: list[str] = field(default_factory=list)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class SceneSnapshot:
    """Semantic scene at one instant in time."""

    scene_id: str
    timestamp: float
    confidence: float
    uncertainty_level: str  # "LOW" | "MEDIUM" | "HIGH"
    present_object_classes: list[str]
    present_person_ids: list[str]
    dominant_activity: str  # see ACTIVITY_* constants
    activity_label: str
    spatial_context: str
    human_proximity_m: float  # inf = no persons
    is_crowded: bool
    stale_modalities: list[str]
    description: str


# ── Activity labels ───────────────────────────────────────────────────────────

ACTIVITY_IDLE = "idle"
ACTIVITY_INTERACTING = "interacting"
ACTIVITY_NAVIGATING = "navigating"
ACTIVITY_SERVING = "serving"
ACTIVITY_CROWDED = "crowded"

_ACTIVITY_CODE = {
    ACTIVITY_IDLE: 0,
    ACTIVITY_INTERACTING: 1,
    ACTIVITY_NAVIGATING: 2,
    ACTIVITY_SERVING: 3,
    ACTIVITY_CROWDED: 4,
}


class SceneAnalyzer:
    """
    Analyzes a FusionContext and produces:
    * A SceneSnapshot summarising the current state.
    * Zero or more ContextEvents describing what has *changed*.

    Call analyze() once per perception cycle.
    """

    def __init__(self, cfg: SceneConfig) -> None:
        self.cfg = cfg
        self._last_snapshot: SceneSnapshot | None = None
        self._last_event_time: float = 0.0

    # ── Main entry point ──────────────────────────────────────────────────────

    def analyze(self, ctx: FusionContext) -> tuple[SceneSnapshot, list[ContextEvent]]:
        """
        Returns (snapshot, events).

        events is empty when the scene has not changed meaningfully since the
        last call, or on the very first call.
        """
        activity, activity_label = self._infer_activity(ctx)
        spatial = self._infer_spatial_context(ctx)
        proximity = ctx.nearest_person_distance_m
        confidence = self._compute_confidence(ctx)
        object_classes = sorted({o.class_name for o in ctx.objects})
        person_ids = [p.person_id for p in ctx.persons]

        snapshot = SceneSnapshot(
            scene_id=str(uuid.uuid4()),
            timestamp=ctx.timestamp,
            confidence=confidence,
            uncertainty_level=ctx.uncertainty_level,
            present_object_classes=object_classes,
            present_person_ids=person_ids,
            dominant_activity=activity,
            activity_label=activity_label,
            spatial_context=spatial,
            human_proximity_m=proximity,
            is_crowded=len(ctx.persons) >= self.cfg.crowded_threshold,
            stale_modalities=list(ctx.stale_modalities),
            description=self._describe(ctx, activity, spatial),
        )

        events = self._detect_events(snapshot)
        self._last_snapshot = snapshot
        return snapshot, events

    # ── Activity inference ────────────────────────────────────────────────────

    def _infer_activity(self, ctx: FusionContext) -> tuple[str, str]:
        if ctx.is_moving:
            return ACTIVITY_NAVIGATING, "navigating"

        if ctx.has_speech:
            return ACTIVITY_INTERACTING, "interacting"

        if ctx.persons:
            prox = ctx.nearest_person_distance_m
            if len(ctx.persons) >= self.cfg.crowded_threshold:
                return ACTIVITY_CROWDED, "crowded"
            if prox <= self.cfg.interaction_proximity_m:
                return ACTIVITY_SERVING, "serving"
            if prox <= self.cfg.near_person_threshold_m:
                return ACTIVITY_INTERACTING, "interacting"

        return ACTIVITY_IDLE, "idle"

    # ── Spatial context ───────────────────────────────────────────────────────

    def _infer_spatial_context(self, ctx: FusionContext) -> str:
        if len(ctx.persons) >= self.cfg.crowded_threshold:
            return "crowded"
        prox = ctx.nearest_person_distance_m
        if prox <= self.cfg.near_person_threshold_m:
            return "near_person"
        return "open_space"

    # ── Confidence ────────────────────────────────────────────────────────────

    def _compute_confidence(self, ctx: FusionContext) -> float:
        base = 0.90
        penalty = {"LOW": 0.0, "MEDIUM": 0.20, "HIGH": 0.45}.get(ctx.uncertainty_level, 0.20)
        # Object/person confidence average
        all_confs = [o.confidence for o in ctx.objects] + [p.confidence for p in ctx.persons]
        sensor_conf = sum(all_confs) / len(all_confs) if all_confs else 0.75
        return max(0.05, min(1.0, (base - penalty) * sensor_conf))

    # ── Natural language description ──────────────────────────────────────────

    def _describe(self, ctx: FusionContext, activity: str, spatial: str) -> str:
        parts: list[str] = []

        n_persons = len(ctx.persons)
        if n_persons == 0:
            parts.append("no persons detected")
        elif n_persons == 1:
            pid = ctx.persons[0].person_id
            d = ctx.persons[0].distance_m
            dist_str = f" at {d:.1f}m" if not __import__("math").isnan(d) else ""
            parts.append(f"one person ({pid}{dist_str})")
        else:
            parts.append(f"{n_persons} persons detected")

        if ctx.objects:
            classes = sorted({o.class_name for o in ctx.objects})
            parts.append(f"objects: {', '.join(classes)}")

        if ctx.has_speech:
            parts.append(f"speech: '{ctx.speech.text[:40]}'")  # type: ignore[union-attr]

        parts.append(f"activity={activity} spatial={spatial}")

        stale = ctx.stale_modalities
        if stale:
            parts.append(f"stale=[{', '.join(stale)}]")

        return "; ".join(parts)

    # ── Event detection ───────────────────────────────────────────────────────

    def _detect_events(self, snapshot: SceneSnapshot) -> list[ContextEvent]:
        events: list[ContextEvent] = []
        now = time.monotonic()
        prev = self._last_snapshot

        if prev is None:
            return events

        # Debounce: suppress rapid re-triggering
        if (now - self._last_event_time) < self.cfg.event_debounce_sec:
            return events

        prev_ids = set(prev.present_person_ids)
        curr_ids = set(snapshot.present_person_ids)

        # Person arrived
        for pid in sorted(curr_ids - prev_ids):
            events.append(
                ContextEvent(
                    event_type="person_arrived",
                    subject_id=pid,
                    confidence=0.90,
                    description=f"Person {pid} entered the scene",
                )
            )

        # Person left
        for pid in sorted(prev_ids - curr_ids):
            events.append(
                ContextEvent(
                    event_type="person_left",
                    subject_id=pid,
                    confidence=0.90,
                    description=f"Person {pid} left the scene",
                )
            )

        # Activity changed
        if prev.dominant_activity != snapshot.dominant_activity:
            events.append(
                ContextEvent(
                    event_type="activity_changed",
                    subject_id="scene",
                    confidence=snapshot.confidence,
                    prior_value=prev.dominant_activity,
                    new_value=snapshot.dominant_activity,
                    description=(
                        f"Activity changed: {prev.dominant_activity} "
                        f"→ {snapshot.dominant_activity}"
                    ),
                )
            )

        # Crowd formed / dispersed
        if not prev.is_crowded and snapshot.is_crowded:
            events.append(
                ContextEvent(
                    event_type="crowd_formed",
                    subject_id="scene",
                    confidence=0.85,
                    description=f"Scene became crowded ({len(snapshot.present_person_ids)} persons)",
                )
            )
        elif prev.is_crowded and not snapshot.is_crowded:
            events.append(
                ContextEvent(
                    event_type="crowd_dispersed",
                    subject_id="scene",
                    confidence=0.85,
                    description="Crowd has dispersed",
                )
            )

        # Object appeared / disappeared
        prev_objs = set(prev.present_object_classes)
        curr_objs = set(snapshot.present_object_classes)
        for cls in sorted(curr_objs - prev_objs):
            events.append(
                ContextEvent(
                    event_type="object_appeared",
                    subject_id=cls,
                    confidence=0.75,
                    description=f"New object class detected: {cls}",
                )
            )
        for cls in sorted(prev_objs - curr_objs):
            events.append(
                ContextEvent(
                    event_type="object_disappeared",
                    subject_id=cls,
                    confidence=0.70,
                    description=f"Object class no longer visible: {cls}",
                )
            )

        if events:
            self._last_event_time = now

        return events

    def reset(self) -> None:
        """Clear state (e.g. after re-configure)."""
        self._last_snapshot = None
        self._last_event_time = 0.0
