"""
bonbon_perception_ai.understanding.risk_assessor
=================================================
Analyses a FusionContext + SceneSnapshot and emits RiskEvents for situations
that the robot or safety supervisor should react to.

Risk types
----------
person_too_close          robot proximity below critical threshold
person_nearby             proximity below caution threshold (warning)
navigation_uncertainty    robot moving while sensor confidence is HIGH
crowded_area              scene is_crowded flag set
conflicting_commands      same speaker issued rapid contradictory intents
unknown_person            person detected with no known identity
stale_sensors             multiple modalities stale while active
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field

from bonbon_perception_ai.config.perception_config import RiskConfig
from bonbon_perception_ai.fusion.types import FusionContext
from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot

# ── Output type ───────────────────────────────────────────────────────────────


@dataclass
class RiskEvent:
    risk_type: str
    severity: str  # "INFO"|"LOW"|"MEDIUM"|"HIGH"|"CRITICAL"
    confidence: float
    subject_id: str
    description: str
    requires_immediate_action: bool = False
    suggested_action: str = ""
    distance_m: float = -1.0
    risk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def severity_int(self) -> int:
        return {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}.get(self.severity, 0)


# ── Assessor ──────────────────────────────────────────────────────────────────


class RiskAssessor:
    """
    Stateless (per-call) risk evaluator.

    Returns a list of RiskEvents sorted by descending severity.
    """

    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg
        self._last_speech_class: str | None = None
        self._last_speech_speaker: str | None = None
        self._last_speech_time: float = 0.0

    def assess(
        self,
        ctx: FusionContext,
        scene: SceneSnapshot,
        latest_intent_class: str | None = None,
    ) -> list[RiskEvent]:
        risks: list[RiskEvent] = []

        risks.extend(self._check_person_proximity(ctx))
        risks.extend(self._check_navigation_uncertainty(ctx, scene))
        risks.extend(self._check_crowded(scene))
        risks.extend(self._check_stale_sensors(ctx))
        if latest_intent_class is not None:
            risks.extend(self._check_conflicting_commands(ctx, latest_intent_class))

        # Sort: highest severity first
        risks.sort(key=lambda r: r.severity_int, reverse=True)
        return risks

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_person_proximity(self, ctx: FusionContext) -> list[RiskEvent]:
        events: list[RiskEvent] = []
        for person in ctx.persons:
            d = person.distance_m
            if math.isnan(d):
                continue
            if d < self.cfg.critical_proximity_m:
                events.append(
                    RiskEvent(
                        risk_type="person_too_close",
                        severity="CRITICAL",
                        confidence=0.95,
                        subject_id=person.person_id,
                        distance_m=d,
                        description=(
                            f"Person {person.person_id} is {d:.2f}m away "
                            f"(critical threshold {self.cfg.critical_proximity_m}m)"
                        ),
                        requires_immediate_action=True,
                        suggested_action="stop",
                    )
                )
            elif d < self.cfg.high_proximity_m:
                events.append(
                    RiskEvent(
                        risk_type="person_too_close",
                        severity="HIGH",
                        confidence=0.90,
                        subject_id=person.person_id,
                        distance_m=d,
                        description=(
                            f"Person {person.person_id} is {d:.2f}m away "
                            f"(high threshold {self.cfg.high_proximity_m}m)"
                        ),
                        requires_immediate_action=True,
                        suggested_action="slow_down",
                    )
                )
            elif d < self.cfg.caution_proximity_m:
                events.append(
                    RiskEvent(
                        risk_type="person_nearby",
                        severity="MEDIUM",
                        confidence=0.85,
                        subject_id=person.person_id,
                        distance_m=d,
                        description=(f"Person {person.person_id} nearby at {d:.2f}m"),
                        requires_immediate_action=False,
                        suggested_action="proceed_slowly",
                    )
                )
        return events

    def _check_navigation_uncertainty(
        self, ctx: FusionContext, scene: SceneSnapshot
    ) -> list[RiskEvent]:
        if not self.cfg.nav_uncertainty_risk:
            return []
        if not ctx.is_moving:
            return []
        if ctx.uncertainty_level != "HIGH":
            return []
        return [
            RiskEvent(
                risk_type="navigation_with_uncertainty",
                severity="HIGH",
                confidence=0.80,
                subject_id="robot",
                description=(
                    "Robot is navigating while sensor uncertainty is HIGH "
                    f"(stale: {', '.join(ctx.stale_modalities)})"
                ),
                requires_immediate_action=False,
                suggested_action="stop_and_wait",
            )
        ]

    def _check_crowded(self, scene: SceneSnapshot) -> list[RiskEvent]:
        if not scene.is_crowded:
            return []
        return [
            RiskEvent(
                risk_type="crowded_area",
                severity=self.cfg.crowded_severity,
                confidence=0.90,
                subject_id="scene",
                description=(f"Crowded scene with {len(scene.present_person_ids)} persons"),
                requires_immediate_action=False,
                suggested_action="slow_down",
            )
        ]

    def _check_stale_sensors(self, ctx: FusionContext) -> list[RiskEvent]:
        n = len(ctx.stale_modalities)
        if n < 2:
            return []
        severity = "HIGH" if n >= 3 else "MEDIUM"
        return [
            RiskEvent(
                risk_type="stale_sensors",
                severity=severity,
                confidence=1.0,
                subject_id="sensors",
                description=(f"{n} modalities stale: {', '.join(ctx.stale_modalities)}"),
                requires_immediate_action=(n >= 3),
                suggested_action="notify_operator",
            )
        ]

    def _check_conflicting_commands(
        self, ctx: FusionContext, current_class: str
    ) -> list[RiskEvent]:
        """Detect rapid flip between confirm/deny or cancel/order."""
        CONFLICT_PAIRS = {
            frozenset({"confirm", "deny"}),
            frozenset({"cancel", "order_item"}),
            frozenset({"cancel", "navigate_to"}),
        }
        now = time.monotonic()
        events: list[RiskEvent] = []

        if (
            self._last_speech_class is not None
            and (now - self._last_speech_time) < 3.0  # within 3 s
        ):
            pair = frozenset({self._last_speech_class, current_class})
            if pair in CONFLICT_PAIRS:
                speaker = ctx.speech.speaker_id if ctx.speech else "unknown"
                events.append(
                    RiskEvent(
                        risk_type="conflicting_commands",
                        severity="LOW",
                        confidence=0.75,
                        subject_id=speaker,
                        description=(
                            f"Conflicting commands from speaker {speaker!r}: "
                            f"{self._last_speech_class!r} then {current_class!r}"
                        ),
                        requires_immediate_action=False,
                        suggested_action="ask_for_clarification",
                    )
                )

        self._last_speech_class = current_class
        self._last_speech_time = now
        if ctx.speech:
            self._last_speech_speaker = ctx.speech.speaker_id

        return events
