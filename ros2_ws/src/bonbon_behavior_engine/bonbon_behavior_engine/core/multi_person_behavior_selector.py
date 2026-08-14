"""MultiPersonBehaviorSelector — turns a multi-person HumanState snapshot into
behavior proposals, implementing the project brief's 10 example behaviors.

Pure logic, no ROS2 dependency. Never issues motion/speech itself — every
candidate it returns is dispatched through the node's EXISTING safety-gated
path (ProposalEvaluator.evaluate(), then the same actuation/TTS dispatch
already used by the single-person callbacks). This module only decides WHAT
to propose and for WHOM; it does not bypass any existing safety gate.

Replaces nothing: bonbon_human_state_fusion already fuses face+voice+text+
gesture per person (HumanState) and bonbon_affective_ai's EmotionAwareResponsePlanner
already maps emotion -> response style (reused here, not reimplemented).
This module adds exactly what neither has: focus-person selection across
MULTIPLE simultaneous people, and the cross-signal combination rules
(emotion+intent, gesture+identity, lifecycle+lifecycle-history) that only
make sense once you can see every tracked person at once.
"""

from __future__ import annotations

from dataclasses import dataclass

SPEAKING = "speaking"

_SAFETY_GESTURES = frozenset({"stop_palm", "raised_hand"})
_POINTING_GESTURES = frozenset({"pointing_left", "pointing_right", "pointing_forward"})
_QUESTION_INTENTS = frozenset({"ask_question", "help_request"})
_ARRIVAL_GESTURES = frozenset({"wave"})
_ARRIVAL_LIFECYCLE_STATES = frozenset({"present", "reappeared"})


@dataclass
class BehaviorCandidate:
    proposal_type: str  # 'speak' | 'gesture' | 'pause' | 'alert_operator'
    content: str
    source: str  # rule name, for decision logs
    urgency: float
    person_track_id: str
    tts_emotion: str = "neutral"
    speed_scale: float = 1.0


def select_focus_person(human_states: list) -> str:
    """Picks who the robot should be paying attention to this cycle.

    Priority (highest first): actively speaking > active_interaction
    lifecycle > highest urgency > most recently reappeared/arrived. Returns
    "" if nobody is currently present.

    Implements rule 5 ("multiple people speak -> focus on active speaker").
    """
    present = [hs for hs in human_states if hs.lifecycle_state != "left_scene"]
    if not present:
        return ""

    speaking = [hs for hs in present if hs.active_speaker_status == SPEAKING]
    if speaking:
        return max(speaking, key=lambda hs: hs.urgency_level).person_track_id

    interacting = [hs for hs in present if hs.lifecycle_state == "active_interaction"]
    if interacting:
        return max(interacting, key=lambda hs: hs.urgency_level).person_track_id

    most_urgent = max(present, key=lambda hs: hs.urgency_level)
    if most_urgent.urgency_level > 0.0:
        return most_urgent.person_track_id

    reappeared = [hs for hs in present if hs.lifecycle_state == "reappeared"]
    if reappeared:
        return reappeared[0].person_track_id

    return present[0].person_track_id


class MultiPersonBehaviorSelector:
    """Stateful only in the sense of "have we already greeted this person" —
    all actual decision logic is the pure functions below. State is per
    person_track_id and is explicitly forgotten on departure (see forget())
    so a later, genuinely different arrival is never silently skipped.
    """

    def __init__(self) -> None:
        self._greeted_arrival: set[str] = set()
        self._greeted_by_name: set[str] = set()

    def forget(self, person_track_id: str) -> None:
        self._greeted_arrival.discard(person_track_id)
        self._greeted_by_name.discard(person_track_id)

    # ── Rule 6: safety gesture from ANYONE nearby pauses and asks confirmation ──

    def decide_safety_gesture_response(self, human_states: list) -> BehaviorCandidate | None:
        for hs in human_states:
            if hs.lifecycle_state == "left_scene":
                continue
            if hs.current_gesture in _SAFETY_GESTURES:
                return BehaviorCandidate(
                    proposal_type="pause",
                    content="Pausing — please confirm if you'd like me to continue.",
                    source="rule6_safety_gesture",
                    urgency=1.0,
                    person_track_id=hs.person_track_id,
                    tts_emotion="calm",
                )
        return None

    # ── Rule 1: new person arrives and waves -> greet ───────────────────────

    def decide_arrival_greeting(self, hs) -> BehaviorCandidate | None:
        if hs.person_track_id in self._greeted_arrival:
            return None
        if hs.lifecycle_state not in _ARRIVAL_LIFECYCLE_STATES:
            return None
        if hs.current_gesture not in _ARRIVAL_GESTURES:
            return None
        self._greeted_arrival.add(hs.person_track_id)
        # First-time visitors (no known_person_id -- see rule2's recall
        # buffer) get a brief orientation to what the robot can actually
        # do, not just a generic "hello": many people in an Indian
        # hospital setting will never have interacted with a service
        # robot before and won't know to ask it anything specific.
        # Returning/recognized people keep the short greeting -- they
        # already know what BonBon does, and repeating the orientation
        # on every visit would be tedious rather than helpful.
        if hs.known_person_id:
            content = "Hello! I'm BonBon. How can I help you today?"
        else:
            content = (
                "Hello! I'm BonBon, the hospital's assistant robot. "
                "I can help you find a department, check your appointment or "
                "token, or answer questions about the hospital. "
                "How can I help you today?"
            )
        return BehaviorCandidate(
            proposal_type="speak",
            content=content,
            source="rule1_arrival_wave",
            urgency=0.2,
            person_track_id=hs.person_track_id,
            tts_emotion="warm",
        )

    # ── Rule 2: known person speaks -> respond by name ──────────────────────

    def decide_known_person_greeting(
        self, hs, privacy_allows_name: bool
    ) -> BehaviorCandidate | None:
        if not privacy_allows_name or not hs.known_person_id:
            return None
        if hs.active_speaker_status != SPEAKING:
            return None
        if hs.person_track_id in self._greeted_by_name:
            return None
        self._greeted_by_name.add(hs.person_track_id)
        return BehaviorCandidate(
            proposal_type="speak",
            content=f"Hello {hs.known_person_id}, good to see you again!",
            source="rule2_known_person_speaks",
            urgency=0.2,
            person_track_id=hs.person_track_id,
            tts_emotion="warm",
        )

    # ── Rule 8: confused expression + question -> slow explanation ─────────

    def decide_confused_question_response(self, hs) -> BehaviorCandidate | None:
        if hs.emotional_state != "confused":
            return None
        if hs.text_intent not in _QUESTION_INTENTS:
            return None
        return BehaviorCandidate(
            proposal_type="speak",
            content="Let me explain that more slowly.",
            source="rule8_confused_question",
            urgency=0.3,
            person_track_id=hs.person_track_id,
            tts_emotion="calm",
            speed_scale=0.8,
        )

    # ── Rule 7: angry/stressed voice -> calm supportive style ───────────────
    # Deliberately limited to 'angry'/'frustrated' — 'distressed'/'fearful'
    # are already exclusively handled by behavior_engine_node's older
    # single-focus HumanEmotionState path (EmotionAwareResponsePlanner via
    # _dispatch_emotion_response). Covering them here too would double-dispatch
    # the same event through two independent paths.

    def decide_calm_supportive_response(self, hs) -> BehaviorCandidate | None:
        if hs.emotional_state not in ("angry", "frustrated"):
            return None
        return BehaviorCandidate(
            proposal_type="speak",
            content="I understand. Let me help you with that.",
            source="rule7_calm_supportive",
            urgency=0.4,
            person_track_id=hs.person_track_id,
            tts_emotion="calm",
            speed_scale=0.85,
        )

    # ── Rule 10: person points a direction -> confirm + spatial context ────

    def decide_pointing_confirmation(self, hs) -> BehaviorCandidate | None:
        if hs.current_gesture not in _POINTING_GESTURES:
            return None
        direction = hs.current_gesture.replace("pointing_", "")
        return BehaviorCandidate(
            proposal_type="speak",
            content=f"Did you mean over there, to the {direction}?",
            source="rule10_pointing_confirmation",
            urgency=0.3,
            person_track_id=hs.person_track_id,
            tts_emotion="neutral",
        )

    # ── Rule 3: person leaves -> close session ──────────────────────────────
    # bonbon_multi_person_tracker's own loss_grace_sec IS the "after timeout"
    # — left_scene only fires once that grace window has already elapsed, so
    # no second timeout layer is needed here.

    def decide_departure_close_session(self, hs) -> BehaviorCandidate | None:
        if hs.lifecycle_state != "left_scene":
            return None
        self.forget(hs.person_track_id)
        return BehaviorCandidate(
            proposal_type="gesture",
            content="rest_pose",
            source="rule3_departure",
            urgency=0.1,
            person_track_id=hs.person_track_id,
        )


def apply_child_safety_modifier(
    candidate: BehaviorCandidate, is_child_nearby: bool
) -> BehaviorCandidate:
    """Rule 9: child near robot -> slow movement, no sudden gestures.

    Caps speed_scale and downgrades any gesture proposal to a gentle one —
    applied to whatever decision was already made, not a standalone proposal.
    """
    if not is_child_nearby:
        return candidate
    capped_speed = min(candidate.speed_scale, 0.7)
    content = candidate.content
    if candidate.proposal_type == "gesture" and candidate.content not in (
        "rest_pose",
        "listening_pose",
    ):
        content = "listening_pose"  # never a sudden/expressive gesture near a child
    return BehaviorCandidate(
        proposal_type=candidate.proposal_type,
        content=content,
        source=candidate.source + "+child_safety",
        urgency=candidate.urgency,
        person_track_id=candidate.person_track_id,
        tts_emotion=candidate.tts_emotion,
        speed_scale=capped_speed,
    )
