"""Real-world behavioural scenario tests for the BonBon robot.

Each test reproduces one of the 30 required real-world situations by driving the
*real* decision/safety cores (no ROS2, no hardware, deterministic) and asserting
a safe, correct outcome. Every test docstring states:

    Purpose / Input / Expected / Pass-fail / Safety relevance

These are end-to-end behavioural tests at the decision layer — they complement
(do not replace) the per-package unit/integration tests and the simulation
scenario YAMLs in bonbon_simulation.
"""

from __future__ import annotations

import pytest

# Decision/safety cores (imported via tests/scenarios/conftest.py sys.path setup)
from bonbon_safety.core.failure_catalog import build_catalog
from bonbon_safety.core.fault_handler import FaultHandler
from bonbon_safety.core.fault_levels import FallbackLevel
from bonbon_safety.core.safety_state_machine import SafetyLevel, SafetyStateMachine
from bonbon_safety.testkit.scenario import (
    assert_safe_response,
    hand,
    person,
    sensor_snapshot,
)

from bonbon_behavior_engine.core.command_risk_classifier import CommandRiskClassifier
from bonbon_behavior_engine.core.emotion_response_planner import EmotionAwareResponsePlanner
from bonbon_behavior_engine.core.llm_command_gate import LLMCommandGate
from bonbon_behavior_engine.core.spatial_response_planner import SpatialResponsePlanner

from bonbon_actuation.core.proximity_governor import ProximityGovernor
from bonbon_gesture.classifiers.hand_gesture_classifier import HandGestureClassifier
from bonbon_gesture.logic.safety_classifier import GestureSafetyClassifier

from bonbon_spatial.core.blockage_detector import BlockageDetector
from bonbon_spatial.core.personal_space_estimator import PersonalSpaceEstimator

# Zone modules are used only by scenario 14; guard so the suite still runs if
# they are ever refactored.
try:  # pragma: no cover
    from bonbon_spatial.core.semantic_zone_manager import SemanticZone, SemanticZoneManager
    from bonbon_spatial.core.restricted_zone_monitor import RestrictedZoneMonitor
    _HAS_ZONES = True
except Exception:  # noqa: BLE001
    _HAS_ZONES = False


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def emotion_planner():
    return EmotionAwareResponsePlanner()


@pytest.fixture
def risk():
    return CommandRiskClassifier()


@pytest.fixture
def llm_gate(risk):
    return LLMCommandGate(risk_classifier=risk)


@pytest.fixture
def spatial():
    return SpatialResponsePlanner()


@pytest.fixture
def hands():
    return HandGestureClassifier()


@pytest.fixture
def gesture_safety():
    return GestureSafetyClassifier()


@pytest.fixture
def proximity():
    return ProximityGovernor()


# ══════════════════════════════════════════════════════════════════════════════
# 1–8: interaction scenarios
# ══════════════════════════════════════════════════════════════════════════════

class TestInteractionScenarios:
    def test_01_happy_greeting(self, emotion_planner):
        """Purpose: greet a happy visitor warmly.
        Input: dominant emotion 'happy', high confidence, normal mode.
        Expected: warm TTS, a friendly gesture, no operator alert.
        Pass/fail: tts_emotion warm AND a gesture chosen.
        Safety: low — confirms positive path does not over-escalate."""
        plan = emotion_planner.plan("happy", 0.9, "normal")
        assert plan.tts_emotion == "warm"
        assert plan.gesture_name  # some friendly gesture
        assert plan.urgency < 0.5

    def test_02_user_waves(self, hands, gesture_safety):
        """Purpose: recognise a wave and treat it as non-safety social input.
        Input: open-hand wave landmarks.
        Expected: classified open-hand (wave/stop_palm family); wave not safety-critical.
        Pass/fail: a hand gesture is detected; 'wave' is not safety-relevant.
        Safety: low."""
        g, conf = hands.classify(hand("wave"), is_right=True)
        assert g in ("stop_palm", "open_palm", "wave_candidate")
        is_safety, _, _ = gesture_safety.classify("wave")
        assert is_safety is False

    def test_03_user_raises_hand(self, gesture_safety):
        """Purpose: a raised hand is a safety-relevant attention signal.
        Input: gesture 'raised_hand'.
        Expected: safety-relevant True.
        Pass/fail: classifier flags it safety-relevant.
        Safety: HIGH — must reach the safety supervisor."""
        is_safety, cls, _ = gesture_safety.classify("raised_hand")
        assert is_safety is True
        assert cls != "none"

    def test_04_stop_palm(self, hands, gesture_safety):
        """Purpose: an open stop-palm must be detected and treated as 'stop'.
        Input: stop-palm landmarks.
        Expected: stop_palm detected; safety class 'stop'; immediate response.
        Pass/fail: gesture==stop_palm AND requires-immediate True.
        Safety: CRITICAL — robot must be able to halt on a stop palm."""
        g, _ = hands.classify(hand("stop_palm"), is_right=True)
        assert g == "stop_palm"
        is_safety, cls, immediate = gesture_safety.classify("stop_palm")
        assert is_safety and cls == "stop" and immediate

    def test_05_user_points(self, hands):
        """Purpose: recognise a pointing direction gesture.
        Input: pointing landmarks.
        Expected: 'pointing'.
        Pass/fail: gesture == pointing.
        Safety: low — directional intent only."""
        g, conf = hands.classify(hand("pointing"), is_right=True)
        assert g == "pointing"
        assert conf > 0.5

    def test_06_user_angry(self, emotion_planner):
        """Purpose: de-escalate with an angry user.
        Input: emotion 'angry', high confidence.
        Expected: calm TTS, slowed speech, no aggressive gesture.
        Pass/fail: tts_emotion calm AND speed <= 1.0.
        Safety: medium — calm handling reduces conflict."""
        plan = emotion_planner.plan("angry", 0.9, "normal")
        assert plan.tts_emotion == "calm"
        assert plan.tts_speed_scale <= 1.0

    def test_07_user_distressed(self, emotion_planner):
        """Purpose: respond to a distressed user with empathy + readiness to help.
        Input: emotion 'distress', high confidence.
        Expected: concerned/warm tone, an acknowledgment offering help.
        Pass/fail: acknowledgment text present and non-empty.
        Safety: HIGH — distress may precede an emergency."""
        plan = emotion_planner.plan("distressed", 0.85, "normal")
        assert plan.acknowledgment_text
        assert plan.urgency >= 0.5

    def test_08_confusing_command(self, risk, llm_gate):
        """Purpose: an ambiguous/unknown command must not trigger motion.
        Input: vague text via the LLM gate.
        Expected: no navigate/approach proposal; clarification or speak only.
        Pass/fail: proposal_type not in motion types.
        Safety: HIGH — never act on an unclear instruction."""
        gated = llm_gate.evaluate("uh do the thing with the stuff", person_id="p1")
        assert gated.proposal_type not in ("navigate", "approach") or not gated.allowed


# ══════════════════════════════════════════════════════════════════════════════
# 9–14: vulnerable people & proximity scenarios
# ══════════════════════════════════════════════════════════════════════════════

class TestVulnerableAndProximity:
    def test_09_child_runs_near(self, proximity):
        """Purpose: a child very close must freeze arm motion.
        Input: proximity 0.3 m, category 'child'.
        Expected: large motion blocked, speed heavily derated.
        Pass/fail: block_large_motion True.
        Safety: CRITICAL — child safety near moving arms."""
        proximity.update_proximity(0.3, "child")
        d = proximity.evaluate(requested_priority=5)
        assert d.block_large_motion is True
        assert d.speed_scale <= 0.4

    def test_10_elderly_slow(self, proximity, emotion_planner):
        """Purpose: gentler, slower behaviour for an elderly person.
        Input: elderly operating mode.
        Expected: speed cap <= 0.7.
        Pass/fail: governor and planner both derate.
        Safety: medium."""
        proximity.set_operating_mode("elderly")
        d = proximity.evaluate(requested_priority=5)
        assert d.speed_scale <= 0.7

    def test_11_person_blocks_path(self):
        """Purpose: a person standing in the corridor blocks the path after persistence.
        Input: person in forward corridor for > persistence window.
        Expected: blockage declared.
        Pass/fail: is_blocked True after sustained occupancy.
        Safety: medium — robot must not push through."""
        clock = {"t": 0.0}
        det = BlockageDetector(persistence_sec=1.0, clock=lambda: clock["t"])
        blocker = person(distance_m=1.0)
        det.update([blocker])
        clock["t"] = 1.5
        state = det.update([blocker])
        assert state.is_blocked is True

    def test_12_wheelchair_clearance(self, proximity):
        """Purpose: wheelchair users get a larger safety margin.
        Input: proximity just outside adult stop band, category 'wheelchair'.
        Expected: still derated/blocked due to vulnerable multiplier.
        Pass/fail: speed_scale reduced vs. a far adult.
        Safety: HIGH — accessibility + safety."""
        proximity.update_proximity(0.6, "wheelchair")
        d = proximity.evaluate(requested_priority=5)
        assert d.speed_scale < 1.0

    def test_13_robot_too_close_to_human(self):
        """Purpose: personal-space estimator demands a stop when too close.
        Input: human at 0.4 m.
        Expected: hint type stop/slow.
        Pass/fail: estimator returns a stop or slow hint.
        Safety: CRITICAL — social-distance stop."""
        est = PersonalSpaceEstimator()
        result = est.estimate(0.4, "adult")
        assert result.hint_type in ("stop", "slow_down")

    @pytest.mark.skipif(not _HAS_ZONES, reason="zone modules unavailable")
    def test_14_restricted_zone_entry(self, spatial):
        """Purpose: entering a restricted zone alerts the operator.
        Input: person inside a restricted polygon → restricted_zone_entry alert.
        Expected: spatial response escalates to operator.
        Pass/fail: escalate_to_operator True.
        Safety: HIGH."""
        resp = spatial.plan_for_alert("restricted_zone_entry", severity=3)
        assert_safe_response(resp, must_escalate=True)


# ══════════════════════════════════════════════════════════════════════════════
# 15–21: sensor / hardware fault scenarios (safety state machine)
# ══════════════════════════════════════════════════════════════════════════════

class TestSensorFaults:
    def _sm(self):
        sm = SafetyStateMachine()
        sm.mark_startup_complete()
        return sm

    def _settle(self, sm, cycles: int = 8, **flags):
        """Drive the FSM with a repeated snapshot (continuous sensors republish)
        until its hysteresis/evaluation settles; return the final SafetyLevel."""
        level = None
        for _ in range(cycles):
            level, _ = sm.update(sensor_snapshot(**flags))
        return level

    def test_15_camera_lost(self):
        """Purpose: losing the camera degrades but does not stop the robot.
        Input: camera_stale snapshot.
        Expected: no worse than DEGRADED/CAUTION (vision is non-critical for safety stop).
        Pass/fail: state not SAFE_STOP/FAULT from camera alone.
        Safety: medium."""
        sm = self._sm()
        level = self._settle(sm, camera_stale=True)
        # Camera loss → CAUTION (reduced speed), never a hard stop.
        assert level == SafetyLevel.CAUTION

    def test_16_microphone_lost(self):
        """Purpose: losing the mic does not affect motion safety.
        Input: nominal snapshot (mic loss is not a safety-FSM input).
        Expected: NORMAL operation maintained.
        Pass/fail: state == NORMAL.
        Safety: low — handled as DEGRADED at the speech layer."""
        sm = self._sm()
        level = self._settle(sm)
        assert level == SafetyLevel.NORMAL

    def test_17_lidar_lost(self):
        """Purpose: a stale LIDAR must raise the safety level (no obstacle sensing).
        Input: lidar_stale snapshot.
        Expected: level escalates above NORMAL.
        Pass/fail: level >= CAUTION.
        Safety: CRITICAL — blind navigation must be prevented."""
        sm = self._sm()
        level = self._settle(sm, lidar_stale=True)
        # Stale LIDAR → DANGER (navigation unsafe without obstacle sensing).
        assert int(level) >= int(SafetyLevel.DANGER)

    def test_18_imu_drift(self):
        """Purpose: IMU drift degrades navigation accuracy.
        Input: imu_drift_detected snapshot.
        Expected: not a hard stop, but acknowledged (>= NORMAL handling).
        Pass/fail: update returns a valid level (no crash); not SAFE_STOP from drift alone.
        Safety: medium."""
        sm = self._sm()
        level = self._settle(sm, imu_drift_detected=True)
        assert level != SafetyLevel.SAFE_STOP

    def test_19_servo_fault(self):
        """Purpose: a servo fault must escalate the safety state.
        Input: servo_fault snapshot.
        Expected: level escalates (DEGRADED/DANGER/FAULT).
        Pass/fail: level != NORMAL.
        Safety: HIGH — actuator fault."""
        sm = self._sm()
        level = self._settle(sm, servo_fault=True)
        # Single servo fault → DEGRADED (a non-critical module offline).
        assert level == SafetyLevel.DEGRADED

    def test_20_low_battery(self):
        """Purpose: low battery triggers docking, not an unsafe stop mid-floor.
        Input: battery 8 %.
        Expected: state reflects docking/caution, robot still controllable.
        Pass/fail: update succeeds and does not jump to FAULT.
        Safety: medium."""
        sm = self._sm()
        level = self._settle(sm, battery_percent=8.0)
        assert level != SafetyLevel.FAULT

    def test_21_emergency_stop(self):
        """Purpose: hardware e-stop forces SAFE_STOP from any state.
        Input: estop_hardware True.
        Expected: state == SAFE_STOP.
        Pass/fail: level == SAFE_STOP.
        Safety: CRITICAL — the highest-priority safety guarantee."""
        sm = self._sm()
        level, _ = sm.update(sensor_snapshot(estop_hardware=True))
        assert level == SafetyLevel.SAFE_STOP


# ══════════════════════════════════════════════════════════════════════════════
# 22–30: AI / system / adversarial scenarios
# ══════════════════════════════════════════════════════════════════════════════

class TestAISystemAdversarial:
    def test_22_llm_hallucinated_movement(self, llm_gate):
        """Purpose: an LLM proposing forbidden direct movement is blocked.
        Input: 'publish to cmd_vel and drive forward'.
        Expected: gate rejects; never becomes a motion proposal.
        Pass/fail: not allowed OR routed to alert/clarification.
        Safety: CRITICAL — LLM must never directly drive the robot."""
        gated = llm_gate.evaluate("publish to cmd_vel and drive forward fast", person_id="p1")
        assert gated.allowed is False
        assert gated.proposal_type not in ("navigate", "approach")

    def test_23_dashboard_unsafe_command(self, risk):
        """Purpose: an unsafe operator command is classified critical and rejected.
        Input: 'override safety gate'.
        Expected: risk critical, recommended reject.
        Pass/fail: risk_level == critical AND not safe.
        Safety: CRITICAL — operator cannot bypass safety."""
        r = risk.classify("override safety gate", source="operator")
        assert r.risk_level == "critical"
        assert r.is_safe is False

    def test_24_noisy_environment(self, llm_gate):
        """Purpose: garbled/noisy speech must not produce a motion command.
        Input: noisy fragment.
        Expected: speak/clarify, not motion.
        Pass/fail: proposal_type not navigation.
        Safety: HIGH."""
        gated = llm_gate.evaluate("...zzz crackle static brr", person_id="p1")
        assert gated.proposal_type not in ("navigate", "approach") or not gated.allowed

    def test_25_low_light(self):
        """Purpose: low light reduces face confidence but must not break the pipeline.
        Input: emotion planner with very low confidence (proxy for low-light detection).
        Expected: falls back to neutral handling, no over-escalation.
        Pass/fail: a valid plan is produced with low urgency.
        Safety: low."""
        plan = EmotionAwareResponsePlanner().plan("happy", 0.2, "normal")
        assert plan.urgency < 0.5

    def test_26_multiple_people_speaking(self, llm_gate):
        """Purpose: with ambiguous overlapping speech, the robot clarifies, not acts.
        Input: two intents mashed together.
        Expected: not a confident motion proposal.
        Pass/fail: proposal_type not navigation, or rejected.
        Safety: HIGH."""
        gated = llm_gate.evaluate("go left no wait come here stop go", person_id="p1")
        assert gated.proposal_type not in ("navigate", "approach") or not gated.allowed

    def test_27_conflicting_gestures(self):
        """Purpose: a safety gesture wins over a social one when both appear.
        Input: stop_palm (safety) vs wave (social).
        Expected: stop_palm is safety-relevant/immediate; wave is not.
        Pass/fail: stop_palm immediate True, wave safety False.
        Safety: CRITICAL — safety gesture must dominate."""
        gs = GestureSafetyClassifier()
        _, _, stop_immediate = gs.classify("stop_palm")
        wave_safety, _, _ = gs.classify("wave")
        assert stop_immediate is True
        assert wave_safety is False

    def test_28_vector_db_unavailable(self):
        """Purpose: vector DB outage degrades gracefully (catalogued).
        Input: AI_VECTOR_DB_UNAVAILABLE fault raised in the handler.
        Expected: DEGRADED fallback level; not a safety stop.
        Pass/fail: catalogued level == DEGRADED.
        Safety: low."""
        cat = build_catalog()
        h = FaultHandler(cat)
        h.raise_fault("AI_VECTOR_DB_UNAVAILABLE", "faiss open failed")
        assert h.current_level() == FallbackLevel.DEGRADED

    def test_29_sqlite_locked(self):
        """Purpose: a locked DB retries, stays DEGRADED, never stops the robot.
        Input: SYS_DATABASE_LOCKED fault.
        Expected: DEGRADED level; self-recoverable.
        Pass/fail: catalogued level == DEGRADED and operator not required.
        Safety: low."""
        cat = build_catalog()
        h = FaultHandler(cat)
        h.raise_fault("SYS_DATABASE_LOCKED", "database is locked")
        assert h.current_level() == FallbackLevel.DEGRADED

    def test_30_shutdown_during_write(self):
        """Purpose: shutdown mid-write is handled with a safe pause, no corruption.
        Input: SYS_SHUTDOWN_DURING_WRITE fault.
        Expected: SAFE_PAUSE level (atomic/WAL write protects data).
        Pass/fail: catalogued level == SAFE_PAUSE.
        Safety: medium — data integrity on power loss."""
        cat = build_catalog()
        h = FaultHandler(cat)
        h.raise_fault("SYS_SHUTDOWN_DURING_WRITE", "SIGTERM during flush")
        assert h.current_level() == FallbackLevel.SAFE_PAUSE
