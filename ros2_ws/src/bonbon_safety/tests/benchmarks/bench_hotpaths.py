"""Cross-cutting latency benchmark for the BonBon safety-critical hot paths.

Measures the *decision/validation* logic on every latency-budgeted path using
the project's real pure-Python cores (no ROS2, no ML weights, no hardware), and
checks each against its budget from ``perf_targets``. This isolates the
software-decision latency from ML-inference / I/O latency (which the
per-package benches — bench_vision/bench_speech/bench_llm — measure).

Run modes
---------
    # latency tests (assert p95/p99 within budget)
    python -m pytest tests/benchmarks/bench_hotpaths.py -q

    # human-readable table
    python tests/benchmarks/bench_hotpaths.py

    # machine-readable JSON (CI / charting)
    python tests/benchmarks/bench_hotpaths.py --json

Hot paths that need real ML or I/O (rag_query, tts_emergency, database_write,
dashboard_status) are intentionally NOT measured here — see the per-package
benchmark scripts and docs/PERFORMANCE.md.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable

# Make sibling packages importable (their cores are pure Python).
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _pkg in (
    "bonbon_behavior_engine",
    "bonbon_actuation",
    "bonbon_gesture",
    "bonbon_spatial",
    "bonbon_safety",
    "bonbon_multi_person_tracker",
    "bonbon_object_intelligence",
    "bonbon_speaker_intelligence",
    "bonbon_human_state_fusion",
    "bonbon_perception_efficiency",
    "bonbon_data_feedback",
    "bonbon_data_stores",
):
    p = os.path.join(_SRC, _pkg)
    if p not in sys.path:
        sys.path.insert(0, p)

from bonbon_safety.core.perf_monitor import LatencyTracker, check_budget
from bonbon_safety.core.perf_targets import build_targets

_TARGETS = build_targets()
_DEFAULT_REPS = 2000


# ── Hot-path workloads (each returns a zero-arg callable) ─────────────────────


def _safety_validation_workload() -> Callable[[], None] | None:
    from bonbon_safety.core.safety_state_machine import SafetyStateMachine
    from bonbon_safety.core.threat_assessor import ThreatAssessor

    sm = SafetyStateMachine()
    sm.mark_startup_complete()
    ta = ThreatAssessor()

    def run():
        ta.update_lidar_scan(1.5)
        ta.update_persons(
            [{"track_id": "p1", "distance_m": 2.0}, {"track_id": "p2", "distance_m": 3.5}]
        )
        snap = ta.build_snapshot()
        sm.update(snap)

    return run


def _emergency_stop_workload() -> Callable[[], None] | None:
    from bonbon_safety.core.safety_state_machine import SafetyStateMachine
    from bonbon_safety.core.threat_assessor import ThreatAssessor

    def run():
        sm = SafetyStateMachine()
        sm.mark_startup_complete()
        ta = ThreatAssessor()
        ta.update_estop(pressed=True)
        snap = ta.build_snapshot()
        sm.update(snap)  # must transition to SAFE_STOP

    return run


def _behavior_decision_workload() -> Callable[[], None] | None:
    try:
        from bonbon_behavior_engine.core.command_risk_classifier import CommandRiskClassifier
    except Exception:
        return None
    clf = CommandRiskClassifier()
    cmds = [
        "go to the lobby and greet the visitor",
        "publish to cmd_vel at full speed",
        "say hello and wave",
    ]
    i = {"n": 0}

    def run():
        clf.classify(cmds[i["n"] % len(cmds)], source="llm")
        i["n"] += 1

    return run


def _actuation_validation_workload() -> Callable[[], None] | None:
    try:
        from bonbon_actuation.core.gesture_library import GestureLibrary
        from bonbon_actuation.core.servo_validator import ServoValidator
    except Exception:
        return None
    v = ServoValidator()
    gesture = GestureLibrary.get("wave")
    targets = gesture.keyframes[0].targets if gesture and gesture.keyframes else []

    def run():
        v.validate(targets)

    return run


def _gesture_event_workload() -> Callable[[], None] | None:
    try:
        from bonbon_gesture.classifiers.hand_gesture_classifier import HandGestureClassifier
    except Exception:
        return None
    clf = HandGestureClassifier()
    import math

    lm = []
    for j in range(21):
        ang = (j / 21) * 2 * math.pi
        lm.append((320 + 20 * math.cos(ang), 240 + 20 * math.sin(ang), 0.0))

    def run():
        clf.classify(lm, is_right=True)

    return run


def _spatial_update_workload() -> Callable[[], None] | None:
    try:
        from bonbon_spatial.core.blockage_detector import BlockageDetector
        from bonbon_spatial.core.dynamic_obstacle_predictor import DynamicObstaclePredictor
    except Exception:
        return None
    from dataclasses import dataclass

    @dataclass
    class _E:
        entity_id: str
        x: float
        y: float
        vx: float = 0.0
        vy: float = 0.0
        entity_type: str = "person"

    pred = DynamicObstaclePredictor()
    det = BlockageDetector()
    ents = [_E(f"p{k}", 2.0 + k, 0.3 * k, -0.5, 0.0) for k in range(5)]

    def run():
        pred.predict_all(ents)
        det.update(ents)

    return run


def _person_tracking_workload() -> Callable[[], None] | None:
    try:
        from bonbon_multi_person_tracker.core.multi_person_scene_manager import (
            MultiPersonSceneManager,
        )
        from bonbon_multi_person_tracker.core.person_record import RawPersonDetection
    except Exception:
        return None
    mgr = MultiPersonSceneManager()
    dets = [RawPersonDetection(f"r{k}", x=float(k), y=0.0) for k in range(5)]
    mgr.update(dets)  # confirm tracks so steady-state matching is measured

    def run():
        mgr.update(dets)

    return run


def _object_tracking_workload() -> Callable[[], None] | None:
    try:
        from bonbon_object_intelligence.core.confidence_calibrator import (
            CalibratorConfig,
            ObjectConfidenceCalibrator,
        )
        from bonbon_object_intelligence.core.object_permanence_tracker import (
            ObjectPermanenceTracker,
            RawObjectDetection,
        )
    except Exception:
        return None
    tracker = ObjectPermanenceTracker()
    calib = ObjectConfidenceCalibrator(CalibratorConfig())
    dets = [RawObjectDetection(f"class_{k % 3}", 0.8, float(k), 0.0, 0.0) for k in range(8)]
    tracker.update(dets)

    def run():
        inputs = [(d.class_name, d.confidence, (0, 0, 50, 50)) for d in dets]
        calib.deduplicate(inputs)
        tracker.update(dets)

    return run


def _speaker_turn_workload() -> Callable[[], None] | None:
    try:
        from bonbon_speaker_intelligence.core.audio_visual_associator import (
            TrackedPersonBearing,
        )
        from bonbon_speaker_intelligence.core.speaker_identity_manager import (
            SpeakerIdentityManager,
        )
        from bonbon_speaker_intelligence.core.speaker_turn_builder import SpeakerTurnBuilder
        from bonbon_speaker_intelligence.core.transcript_segment_mapper import (
            DiarizationSegment,
            WordTiming,
        )
        from bonbon_speaker_intelligence.core.voice_emotion_cache import VoiceEmotionCache
    except Exception:
        return None
    builder = SpeakerTurnBuilder(SpeakerIdentityManager(), VoiceEmotionCache())
    segs = [DiarizationSegment("SPEAKER_00", 0.0, 1.5), DiarizationSegment("SPEAKER_01", 1.5, 3.0)]
    words = [
        WordTiming(w, i * 0.3, i * 0.3 + 0.25)
        for i, w in enumerate(["hello", "there", "how", "are", "you"])
    ]
    people = [TrackedPersonBearing("ptrk_1", 10.0), TrackedPersonBearing("ptrk_2", -10.0)]

    def run():
        builder.build_turns(
            segs, words, "hello there how are you", 0.9, doa_deg=10.0, tracked_persons=people
        )

    return run


def _human_state_fusion_workload() -> Callable[[], None] | None:
    try:
        from bonbon_human_state_fusion.core.human_state_fusion_engine import (
            HumanStateFusionEngine,
        )
    except Exception:
        return None
    engine = HumanStateFusionEngine()
    for k in range(5):
        engine.update_person_track(
            f"ptrk_{k}", "", "present", f"person_{k}", float(k), 0.0, 0.0, 0.9
        )
        engine.update_human_emotion_state(f"person_{k}", "happy", 0.8, "warm", 1.0, False)
        engine.update_gesture_event(f"ptrk_{k}", "wave", 0.85, False)

    def run():
        engine.build_all()

    return run


def _perception_budget_cycle_workload() -> Callable[[], None] | None:
    try:
        from bonbon_perception_efficiency.core.degraded_mode_manager import DegradedModeManager
        from bonbon_perception_efficiency.core.load_shedding_controller import (
            LoadSheddingController,
        )
        from bonbon_perception_efficiency.core.perception_budget_manager import (
            BudgetInputs,
            PerceptionBudgetManager,
        )
    except Exception:
        return None
    mgr = PerceptionBudgetManager(
        load_shedding=LoadSheddingController(), degraded_mode=DegradedModeManager()
    )
    inputs = BudgetInputs(
        cpu_overloaded=False,
        memory_pressure=False,
        resource_unavailable=False,
        safety_caution_or_above=False,
        safety_fault_or_above=False,
        focus_person_track_id="ptrk_0",
        person_track_ids=[f"ptrk_{k}" for k in range(5)],
        new_candidate_ids={"ptrk_4"},
    )

    def run():
        mgr.update(inputs)

    return run


def _failure_case_log_write_workload() -> Callable[[], None] | None:
    import tempfile
    from pathlib import Path

    try:
        from bonbon_data_feedback.core.feedback_store import FailureCaseRecord, FeedbackStore
    except Exception:
        return None
    tmpdir = tempfile.mkdtemp(prefix="bench_feedback_")
    store = FeedbackStore(Path(tmpdir) / "bench_feedback.db")
    i = {"n": 0}

    def run():
        store.insert_failure_case(
            FailureCaseRecord(
                case_id="",
                category="gesture",
                signal_name="bench",
                expected_label="wave",
                actual_label="point",
                confidence=0.4,
                person_track_id=f"p{i['n']}",
            )
        )
        i["n"] += 1

    return run


# name → (workload factory, budget name)
_BENCHES = {
    "safety_validation": (_safety_validation_workload, "safety_validation"),
    "emergency_stop_reaction": (_emergency_stop_workload, "emergency_stop_reaction"),
    "behavior_decision": (_behavior_decision_workload, "behavior_decision"),
    "actuation_validation": (_actuation_validation_workload, "actuation_validation"),
    "gesture_event": (_gesture_event_workload, "gesture_event"),
    "spatial_reasoning_update": (_spatial_update_workload, "spatial_reasoning_update"),
    "person_tracking_update": (_person_tracking_workload, "person_tracking_update"),
    "object_tracking_update": (_object_tracking_workload, "object_tracking_update"),
    "speaker_turn_update": (_speaker_turn_workload, "speaker_turn_update"),
    "human_state_fusion": (_human_state_fusion_workload, "human_state_fusion"),
    "perception_budget_cycle": (_perception_budget_cycle_workload, "perception_budget_cycle"),
    "failure_case_log_write": (_failure_case_log_write_workload, "failure_case_log_write"),
}


def run_bench(name: str, reps: int = _DEFAULT_REPS) -> dict | None:
    """Run one benchmark; return a result dict, or None if unavailable."""
    factory, budget_name = _BENCHES[name]
    workload = factory()
    if workload is None:
        return None
    workload()  # warmup (model/JIT/first-call effects)
    tracker = LatencyTracker(budget_name, window=reps)
    for _ in range(reps):
        t0 = time.perf_counter()
        workload()
        tracker.record_s(time.perf_counter() - t0)
    rep = check_budget(tracker, _TARGETS[budget_name])
    st = tracker.stats()
    return {
        "bench": name,
        "reps": st.count,
        "mean_ms": round(st.mean_ms, 4),
        "p50_ms": round(st.p50_ms, 4),
        "p95_ms": round(st.p95_ms, 4),
        "p99_ms": round(st.p99_ms, 4),
        "max_ms": round(st.max_ms, 4),
        "budget_ms": rep.budget_ms,
        "metric": rep.metric,
        "observed_ms": rep.observed_ms,
        "passed": rep.passed,
    }


def run_all(reps: int = _DEFAULT_REPS) -> list[dict]:
    import logging as _logging

    _logging.disable(_logging.CRITICAL)  # silence module logs during timing
    try:
        out = []
        for name in _BENCHES:
            r = run_bench(name, reps)
            if r is not None:
                out.append(r)
        return out
    finally:
        _logging.disable(_logging.NOTSET)


# ── pytest latency tests ──────────────────────────────────────────────────────


def _make_test(name):
    def _test():
        r = run_bench(name, reps=500)
        if r is None:
            import pytest

            pytest.skip(f"{name} core unavailable")
        assert r["passed"], (
            f"{name} {r['metric']}={r['observed_ms']}ms exceeds " f"budget {r['budget_ms']}ms"
        )

    _test.__name__ = f"test_latency_{name}"
    return _test


test_latency_safety_validation = _make_test("safety_validation")
test_latency_emergency_stop_reaction = _make_test("emergency_stop_reaction")
test_latency_behavior_decision = _make_test("behavior_decision")
test_latency_actuation_validation = _make_test("actuation_validation")
test_latency_gesture_event = _make_test("gesture_event")
test_latency_spatial_reasoning_update = _make_test("spatial_reasoning_update")
test_latency_person_tracking_update = _make_test("person_tracking_update")
test_latency_object_tracking_update = _make_test("object_tracking_update")
test_latency_speaker_turn_update = _make_test("speaker_turn_update")
test_latency_human_state_fusion = _make_test("human_state_fusion")
test_latency_perception_budget_cycle = _make_test("perception_budget_cycle")
test_latency_failure_case_log_write = _make_test("failure_case_log_write")


# ── standalone CLI ─────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    as_json = "--json" in argv
    reps = _DEFAULT_REPS
    results = run_all(reps)
    if as_json:
        print(json.dumps(results, indent=2))
        return 0
    print(f"\nBonBon hot-path latency benchmark (reps={reps})")
    print(f"{'bench':<28}{'p50':>8}{'p95':>8}{'p99':>8}{'budget':>9}{'':>3}")
    print("-" * 64)
    for r in results:
        mark = "OK " if r["passed"] else "!! "
        print(
            f"{r['bench']:<28}{r['p50_ms']:>8.3f}{r['p95_ms']:>8.3f}"
            f"{r['p99_ms']:>8.3f}{r['budget_ms']:>9.0f}  {mark}"
        )
    failed = [r["bench"] for r in results if not r["passed"]]
    print("-" * 64)
    print("ALL WITHIN BUDGET" if not failed else f"OVER BUDGET: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
