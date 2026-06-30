"""15 real-world scenario tests for the efficiency/feedback upgrade
(bonbon_perception_efficiency, bonbon_data_feedback, bonbon_affective_ai,
bonbon_vision, bonbon_llm).

Each test exercises the REAL core classes from each package directly (no
mocked business logic) — only the message-passing/ROS2 layer is absent,
consistent with every other test suite in this project (see
test_multi_person_perception_scenarios.py for the established convention
this file follows).

Two scenarios are deliberately scoped to what is actually true rather than
the brief's literal wording, and say so in their docstring:
  - Scenario 10 (LLM calls reduced by intent stability) tests the reusable
    TemporalSmoothingManager primitive a stability gate would be built on —
    no node currently wires it in front of an LLM call.
  - Scenario 11 (repeated-question caching) verifies the LLM call itself is
    skipped on a cache hit; RAG retrieval still runs every cycle (a known,
    documented limitation, not silently glossed over).
"""

from __future__ import annotations

from bonbon_data_feedback.core.failure_case_logger import FailureCaseLogger
from bonbon_data_feedback.core.feedback_store import FeedbackStore
from bonbon_data_feedback.core.privacy_safe_data_policy import PrivacySafeDataPolicy
from bonbon_llm.core.response_cache import ResponseCache
from bonbon_perception_efficiency.core.active_person_focus_manager import (
    BACKGROUND_WEIGHT,
    FULL_FOCUS_WEIGHT,
    ActivePersonFocusManager,
)
from bonbon_perception_efficiency.core.bounded_inference_queue import BoundedInferenceQueue
from bonbon_perception_efficiency.core.confidence_policy_manager import ConfidencePolicyManager
from bonbon_perception_efficiency.core.degraded_mode_manager import DegradedModeManager
from bonbon_perception_efficiency.core.load_shedding_controller import (
    LoadLevel,
    LoadSheddingController,
)
from bonbon_perception_efficiency.core.stale_frame_dropper import StaleFrameDropper
from bonbon_perception_efficiency.core.temporal_smoothing_manager import TemporalSmoothingManager


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# ── 1: Stale frames dropped ─────────────────────────────────────────────────


class TestScenario01StaleFramesDropped:
    """Purpose: a frame that arrived long ago must be flagged stale rather
    than processed as if it were current.
    Setup: StaleFrameDropper(timeout_sec=0.5).
    Input: mark_received(), advance the clock 1.0s, then check().
    Expected: is_stale=True.
    Safety relevance: prevents acting on outdated perception (e.g. a person
    who has since left the frame)."""

    def test_frame_older_than_timeout_is_stale(self):
        clock = _Clock()
        dropper = StaleFrameDropper(timeout_sec=0.5, clock=clock)
        dropper.mark_received()
        clock.advance(1.0)
        result = dropper.check()
        assert result.is_stale is True


# ── 2: Queues bounded ────────────────────────────────────────────────────────


class TestScenario02QueuesBounded:
    """Purpose: inference work submitted faster than it can be processed must
    be rejected once a depth limit is reached, not queued without bound.
    Setup: BoundedInferenceQueue(max_depth=2).
    Input: 3 try_admit() calls with nothing marked complete.
    Expected: the 3rd call is rejected (admitted=False).
    Safety relevance: the audit finding this exists to fix — affective_ai_node
    submitted to its ThreadPoolExecutor with no backpressure."""

    def test_third_admit_rejected_when_queue_full(self):
        queue = BoundedInferenceQueue(max_depth=2)
        assert queue.try_admit().admitted is True
        assert queue.try_admit().admitted is True
        assert queue.try_admit().admitted is False


# ── 3: CPU overload triggers load shedding ──────────────────────────────────


class TestScenario03CpuOverloadTriggersLoadShedding:
    """Purpose: sustained CPU overload must reduce the perception-layer load
    level, not be silently absorbed.
    Setup: LoadSheddingController.
    Input: update(cpu_overloaded=True, ...).
    Expected: level escalates to MINIMAL immediately (no hysteresis delay on
    escalation — only de-escalation waits for sustained recovery).
    Safety relevance: this is the mechanism that frees CPU for safety-critical
    work under load."""

    def test_cpu_overload_escalates_immediately(self):
        ctrl = LoadSheddingController()
        decision = ctrl.update(
            cpu_overloaded=True,
            memory_pressure=False,
            resource_unavailable=False,
            safety_caution_or_above=False,
        )
        assert decision.level == LoadLevel.MINIMAL


# ── 4: Safety has highest priority ──────────────────────────────────────────


class TestScenario04SafetyHasHighestPriority:
    """Purpose: a safety FAULT/SAFE_STOP must put the system into degraded
    perception mode IMMEDIATELY, bypassing the sustained-pressure window
    that load-based degradation requires.
    Setup: DegradedModeManager(sustained_threshold_sec=10.0) — a long window.
    Input: update(load_level=NORMAL, safety_fault_or_above=True) on the very
    first call.
    Expected: is_degraded=True despite load being NORMAL and no time having
    passed — safety state alone is sufficient, never waited out.
    Safety relevance: the Safety Supervisor's authority is never delayed by
    this package's own pressure-sustain logic."""

    def test_safety_fault_degrades_immediately_regardless_of_load(self):
        mgr = DegradedModeManager(sustained_threshold_sec=10.0)
        status = mgr.update(load_level=LoadLevel.NORMAL, safety_fault_or_above=True)
        assert status.is_degraded is True


# ── 5: Active speaker / focus person gets full processing priority ─────────


class TestScenario05ActiveSpeakerPriority:
    """Purpose: the person currently selected as conversational focus must
    receive full processing weight, not be treated the same as everyone else
    in the room.
    Setup: ActivePersonFocusManager, 3 tracked people, one is focus.
    Input: compute_weights(focus_person_track_id='p2', [p1,p2,p3], set()).
    Expected: p2's weight == FULL_FOCUS_WEIGHT (1.0).
    Safety relevance: none directly — an efficiency/UX property; ensures
    compute is not wasted equally on people who are not being addressed."""

    def test_focus_person_gets_full_weight(self):
        mgr = ActivePersonFocusManager()
        weights = {
            w.person_track_id: w.weight
            for w in mgr.compute_weights("p2", ["p1", "p2", "p3"], set())
        }
        assert weights["p2"] == FULL_FOCUS_WEIGHT


# ── 6: Background people get reduced processing ─────────────────────────────


class TestScenario06BackgroundReducedProcessing:
    """Purpose: people who are neither the focus nor a new arrival must get a
    reduced processing weight, not full weight — the actual point of this
    capability (the audit found nothing in the codebase did this).
    Setup: same as scenario 5.
    Input: same compute_weights call.
    Expected: p1 and p3's weight == BACKGROUND_WEIGHT (0.3), strictly less
    than p2's.
    Safety relevance: none directly — efficiency only; a background person
    walking toward the robot is still covered by bonbon_safety's lidar-based
    threat assessment, which is entirely independent of this weighting."""

    def test_non_focus_people_get_background_weight(self):
        mgr = ActivePersonFocusManager()
        weights = {
            w.person_track_id: w.weight
            for w in mgr.compute_weights("p2", ["p1", "p2", "p3"], set())
        }
        assert weights["p1"] == BACKGROUND_WEIGHT
        assert weights["p3"] == BACKGROUND_WEIGHT
        assert weights["p1"] < weights["p2"]


# ── 7: Low-confidence gesture does not trigger ──────────────────────────────


class TestScenario07LowConfidenceGestureNoTrigger:
    """Purpose: a gesture detection below the recommended confidence floor
    must not be treated as a valid trigger.
    Setup: ConfidencePolicyManager (default floors).
    Input: a gesture detection with confidence 0.2 compared against
    floor_for('gesture').minimum_threshold.
    Expected: 0.2 is below the minimum threshold — the policy would reject
    it even in a relaxed/degraded state, since it never recommends going
    below the configured floor.
    Safety relevance: prevents the robot reacting to noise misread as a
    stop-palm or come-here gesture."""

    def test_low_confidence_below_minimum_floor(self):
        mgr = ConfidencePolicyManager()
        floor = mgr.floor_for("gesture")
        assert 0.2 < floor.minimum_threshold


# ── 8: Unstable emotion does not change behaviour ───────────────────────────


class TestScenario08UnstableEmotionNoBehaviorChange:
    """Purpose: a person's emotion flapping between labels frame-to-frame
    must not be reported as stable, so downstream behaviour does not react
    to every flicker.
    Setup: TemporalSmoothingManager(window=5, min_agreement=0.6).
    Input: alternating happy/sad/neutral labels for the same person, no
    single label reaching 60% agreement within the window.
    Expected: is_stable=False on the final update.
    Safety relevance: none directly — prevents jittery, distracting
    expressive behaviour from chasing noisy per-frame emotion estimates."""

    def test_flapping_emotion_labels_never_reach_stability(self):
        mgr = TemporalSmoothingManager(window=5, min_agreement=0.6)
        result = None
        for label in ["happy", "sad", "neutral", "happy", "sad"]:
            result = mgr.update("person_1", label)
        assert result.is_stable is False


# ── 9: A still-tracked person is not zeroed out of compute allocation ──────


class TestScenario09PersonNotDroppedFromFocusTooEarly:
    """Purpose: a person the tracker still considers present (e.g. mid brief-
    occlusion grace period — bonbon_multi_person_tracker's own lifecycle
    machine is what decides THAT, see test_multi_person_perception_scenarios
    Scenario05) must still receive at least background processing weight
    from this package, not be silently dropped to zero just because they
    were not the focus.
    Setup: ActivePersonFocusManager.
    Input: a person_track_id present in person_track_ids but not focus and
    not a new candidate.
    Expected: weight == BACKGROUND_WEIGHT (> 0), never zero — this package
    only ever reduces compute for a tracked person, never eliminates it,
    leaving the "is this person still here at all" decision entirely to the
    tracker's own lifecycle state machine."""

    def test_tracked_non_focus_person_keeps_nonzero_weight(self):
        mgr = ActivePersonFocusManager()
        weights = {
            w.person_track_id: w.weight
            for w in mgr.compute_weights("p_focus", ["p_focus", "p_lingering"], set())
        }
        assert weights["p_lingering"] > 0.0


# ── 10: Reusable stability primitive an intent-gated LLM-call reduction
#        would be built on ─────────────────────────────────────────────────


class TestScenario10IntentStabilityPrimitive:
    """Purpose: demonstrate the reusable building block a future "only call
    the LLM once an intent has been stable for N cycles" gate would use.
    Honest scope note: no node currently wires TemporalSmoothingManager in
    front of an LLM call — bonbon_llm's _process_intent calls the LLM once
    per UserIntent message as it always has. This scenario verifies the
    PRIMITIVE behaves correctly for that purpose, it does not claim the gate
    is live.
    Setup: TemporalSmoothingManager(window=3, min_agreement=0.6).
    Input: the same intent_class repeated 3 times.
    Expected: is_stable=True after the 3rd identical value.
    Safety relevance: none — a latency/cost optimisation primitive."""

    def test_repeated_intent_class_becomes_stable(self):
        mgr = TemporalSmoothingManager(window=3, min_agreement=0.6)
        result = None
        for _ in range(3):
            result = mgr.update("speaker_1", "order_item")
        assert result.is_stable is True
        assert result.stable_label == "order_item"


# ── 11: Repeated LLM query is served from cache, RAG limitation noted ──────


class TestScenario11RepeatedQueryCached:
    """Purpose: an identical question asked again within the same scene/
    safety context must not re-run the expensive LLM inference call.
    Honest scope note: only the LLM inference call is skipped on a cache
    hit. RAG retrieval still runs every cycle to build the context string
    used as part of the cache key (so a context change is correctly
    detected) — full RAG-call elimination on a hit is a documented
    limitation of this implementation, not a silent gap.
    Setup: ResponseCache.
    Input: put() a successful ("ok") response, then get() the same
    (question, context) pair.
    Expected: get() returns the cached text without needing a second LLM
    call — verified by absence of any call, since this test never invokes
    an LLM at all.
    Safety relevance: none directly — cost/latency optimisation; the cached
    text still passes through the safety filter and hallucination guard on
    every use (see ResponseCache module docstring), so caching never
    bypasses safety scrutiny."""

    def test_cache_hit_returns_stored_response_without_recomputing(self):
        cache = ResponseCache()
        cache.put("what time is it", "scene=kitchen;safety=NORMAL", "It's 3pm.", "ok")
        hit = cache.get("what time is it", "scene=kitchen;safety=NORMAL")
        assert hit is not None
        assert hit.text == "It's 3pm."

    def test_changed_context_is_not_served_from_cache(self):
        """A person entering the scene changes the context string, so the
        same question correctly misses the cache rather than returning a
        now-outdated cached answer."""
        cache = ResponseCache()
        cache.put("what do you see", "scene=empty_room", "Nothing.", "ok")
        hit = cache.get("what do you see", "scene=person_present")
        assert hit is None


# ── 12: Database writes batched ─────────────────────────────────────────────


class TestScenario12DatabaseWritesBatched:
    """Purpose: logging many failure cases at once must not require one
    round-trip per row — the audit finding this exists to fix (no
    repository in the project supported batch writes before this package).
    Setup: FeedbackStore against a temp SQLite file.
    Input: insert_failure_cases_batch() with 25 records in one call.
    Expected: all 25 rows land, queryable, from the single call.
    Safety relevance: none directly — write-throughput efficiency."""

    def test_batch_insert_lands_all_rows(self, tmp_path):
        from bonbon_data_feedback.core.feedback_store import FailureCaseRecord

        store = FeedbackStore(tmp_path / "scenario12_feedback.db")
        records = [
            FailureCaseRecord(
                case_id="",
                category="object",
                signal_name="bench",
                expected_label="",
                actual_label="x",
                confidence=0.4,
                person_track_id="",
            )
            for _ in range(25)
        ]
        store.insert_failure_cases_batch(records)
        assert store.count_failure_cases() == 25


# ── 13: Degraded mode activates correctly under sustained pressure ─────────


class TestScenario13DegradedModeActivatesCorrectly:
    """Purpose: degraded mode must activate only once load pressure has been
    SUSTAINED for the configured threshold, never from a single bad cycle —
    and must correctly NOT be active before that threshold is reached.
    Setup: DegradedModeManager(sustained_threshold_sec=5.0) with an
    injectable clock.
    Input: update(MINIMAL, False) at t=0 (not yet degraded), then again at
    t=6 (now sustained past the threshold).
    Expected: is_degraded False at t=0, True at t=6.
    Safety relevance: avoids flapping perception policy in and out of
    degraded mode on transient noise."""

    def test_degrades_only_after_sustained_pressure(self):
        clock = _Clock()
        mgr = DegradedModeManager(sustained_threshold_sec=5.0, clock=clock)
        first = mgr.update(load_level=LoadLevel.MINIMAL, safety_fault_or_above=False)
        assert first.is_degraded is False
        clock.advance(6.0)
        second = mgr.update(load_level=LoadLevel.MINIMAL, safety_fault_or_above=False)
        assert second.is_degraded is True


# ── 14: Raw biometric data is not stored by default ─────────────────────────


class TestScenario14RawBiometricNotStoredByDefault:
    """Purpose: the hard project rule — raw face/audio is never stored
    unless an operator has explicitly enabled debug mode.
    Setup: FailureCaseLogger with PrivacySafeDataPolicy(debug_mode_enabled
    defaulted False — never passed True).
    Input: log() called with a raw_snapshot_path supplied, as a node would
    if it had a frame available.
    Expected: the stored record has has_raw_snapshot=False and an empty
    raw_snapshot_path — the path is silently dropped, not stored.
    Safety relevance: privacy/compliance, explicitly named as a hard rule in
    the project brief."""

    def test_raw_snapshot_path_dropped_without_explicit_debug_mode(self, tmp_path):
        store = FeedbackStore(tmp_path / "scenario14_feedback.db")
        policy = PrivacySafeDataPolicy()  # debug_mode_enabled defaults False
        logger = FailureCaseLogger(store, policy)
        case_id = logger.log(
            "face", "mismatch", "person_a", 0.5, raw_snapshot_path="/tmp/face_001.jpg"
        )
        got = store.get_failure_case(case_id)
        assert got.has_raw_snapshot is False
        assert got.raw_snapshot_path == ""


# ── 15: Failure cases are logged safely (forbidden keys stripped) ──────────


class TestScenario15FailureCasesLoggedSafely:
    """Purpose: even when a caller passes raw biometric data by mistake in
    the general context dict, it must never be persisted — the
    forbidden-key strip applies unconditionally, not just when debug mode
    is off.
    Setup: FailureCaseLogger, debug_mode_enabled=True (the MORE permissive
    setting — this must still hold even then).
    Input: log() with context={'face_embedding': [...], 'frame_idx': 9}.
    Expected: the stored context has no 'face_embedding' key but keeps
    'frame_idx' — selective, not blanket, stripping.
    Safety relevance: privacy/compliance defense-in-depth — protects against
    a caller's mistake, not just the no-snapshot-path-by-default rule."""

    def test_forbidden_context_keys_stripped_even_in_debug_mode(self, tmp_path):
        store = FeedbackStore(tmp_path / "scenario15_feedback.db")
        policy = PrivacySafeDataPolicy(debug_mode_enabled=True)
        logger = FailureCaseLogger(store, policy)
        case_id = logger.log(
            "face",
            "mismatch",
            "person_a",
            0.5,
            context={"face_embedding": [0.1, 0.2, 0.3], "frame_idx": 9},
        )
        got = store.get_failure_case(case_id)
        assert "face_embedding" not in got.context
        assert got.context["frame_idx"] == 9
