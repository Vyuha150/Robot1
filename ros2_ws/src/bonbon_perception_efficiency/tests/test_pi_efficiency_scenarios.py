"""Phase 5 Pi-efficiency scenario tests (the 10 the brief lists).

Each exercises a REAL primitive (LoadSheddingController, FrameSamplingManager,
DegradedModeManager, BoundedInferenceQueue, StaleFrameDropper, the
PiEfficiencyProfile, and bonbon_ai_runtime's RuntimeSelector) — not mocks of
the policy. The point is to prove the efficiency machinery genuinely reduces
load without ever touching safety, on a machine with no Pi.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bonbon_perception_efficiency.core.degraded_mode_manager import DegradedModeManager
from bonbon_perception_efficiency.core.frame_sampling_manager import FrameSamplingManager
from bonbon_perception_efficiency.core.load_shedding_controller import (
    LoadLevel,
    LoadSheddingController,
)
from bonbon_perception_efficiency.core.pi_efficiency_profile import PiEfficiencyProfile
from bonbon_perception_efficiency.core.stale_frame_dropper import StaleFrameDropper


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while not (p / "config" / "pi_efficiency_profile.yaml").is_file():
        if p == p.parent:
            raise RuntimeError("repo root not found")
        p = p.parent
    return p


@pytest.fixture
def profile() -> PiEfficiencyProfile:
    return PiEfficiencyProfile.load(_repo_root() / "config" / "pi_efficiency_profile.yaml")


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# 1. CPU overload triggers degraded mode
def test_cpu_overload_triggers_degraded_mode():
    clock = _Clock()
    shed = LoadSheddingController()
    deg = DegradedModeManager(sustained_threshold_sec=1.0, clock=clock)
    d1 = shed.update(
        cpu_overloaded=True,
        memory_pressure=False,
        resource_unavailable=False,
        safety_caution_or_above=False,
    )
    assert d1.level == LoadLevel.MINIMAL
    deg.update(d1.level, safety_fault_or_above=False)
    clock.advance(2.0)
    status = deg.update(d1.level, safety_fault_or_above=False)
    assert status.is_degraded is True


# 2. thermal warning reduces FPS
def test_thermal_warning_reduces_fps():
    shed = LoadSheddingController()
    fs = FrameSamplingManager()
    nominal = {r.consumer: r.sample_every_n_frames for r in fs.recommend(load_shed_scale=1.0)}
    hot = shed.update(
        cpu_overloaded=False,
        memory_pressure=False,
        resource_unavailable=False,
        safety_caution_or_above=False,
        thermal_overloaded=True,
    )
    assert hot.scale < 1.0
    throttled = {
        r.consumer: r.sample_every_n_frames for r in fs.recommend(load_shed_scale=hot.scale)
    }
    # Higher sample-every-N == lower effective FPS.
    assert throttled["gesture"] > nominal["gesture"]


# 3. Hailo unavailable activates CPU fallback or degraded mode
def test_hailo_unavailable_activates_fallback():
    from bonbon_ai_runtime import (
        HailoDeviceDetector,
        HailoRuntime,
        MockRuntime,
        RuntimeKind,
        RuntimeMode,
        RuntimeSelector,
        RuntimeSpec,
    )

    def factory(kind):
        if kind == RuntimeKind.HAILO:
            return HailoRuntime(
                detector=HailoDeviceDetector(runner=lambda c: None, import_probe=lambda m: False)
            )
        return MockRuntime()

    res = RuntimeSelector(factory=factory).select(
        RuntimeSpec(mode=RuntimeMode.AUTO, runtime_priority=[RuntimeKind.HAILO, RuntimeKind.MOCK])
    )
    assert res.fallback_active is True
    assert res.selected_kind != RuntimeKind.HAILO
    assert "hailo" in res.fallback_reason.lower()


# 4. AI inference timeout does not block safety (backpressure never blocks the
#    caller — a full queue rejects immediately instead of waiting)
def test_inference_backpressure_never_blocks():
    from bonbon_perception_efficiency.core.bounded_inference_queue import BoundedInferenceQueue

    q = BoundedInferenceQueue(max_depth=2)
    assert q.try_admit().admitted is True
    assert q.try_admit().admitted is True
    rejected = q.try_admit()  # full — must reject instantly, not block
    assert rejected.admitted is False
    assert q.depth <= 2


# 5. dashboard still updates during (light) degraded mode
def test_dashboard_not_shed_before_lower_priority_modules(profile):
    first_shed = profile.modules_to_shed(3)
    assert "dashboard" not in first_shed
    # the genuinely optional stuff goes first
    assert "analytics_logging" in first_shed
    assert "background_emotion" in first_shed


# 6. safety remains highest priority (never shed, even under extreme pressure)
def test_safety_never_shed(profile):
    assert profile.rank_of("safety_supervisor") == 1
    assert profile.is_safety_critical("safety_supervisor") is True
    huge = profile.modules_to_shed(999)
    for m in profile.safety_critical_modules():
        assert m not in huge
    assert profile.validate() == []


# 7. background emotion analysis disables first (before the meaningful
#    perception modules)
def test_background_emotion_sheds_before_perception(profile):
    order = profile.shed_order()
    assert order.index("background_emotion") < order.index("gesture_recognition")
    assert order.index("background_emotion") < order.index("person_detection")
    assert "background_emotion" in profile.modules_to_shed(2)


# 8. LLM/RAG throttled under load (event-gated + shed before perception)
def test_llm_and_rag_throttled(profile):
    assert profile.is_event_gated("llm") is True
    assert profile.is_event_gated("rag") is True
    order = profile.shed_order()
    assert order.index("llm") < order.index("human_state_fusion")
    assert order.index("rag") < order.index("human_state_fusion")


# 9. queue size never grows unbounded
def test_queue_never_unbounded():
    from bonbon_perception_efficiency.core.bounded_inference_queue import BoundedInferenceQueue

    q = BoundedInferenceQueue(max_depth=4)
    for _ in range(100):
        q.try_admit()
    assert q.depth <= 4
    assert q.dropped_count > 0


# 10. stale frames are dropped
def test_stale_frames_dropped():
    clock = _Clock()
    dropper = StaleFrameDropper(timeout_sec=0.1, clock=clock)
    dropper.mark_received()
    assert dropper.check().is_stale is False
    clock.advance(0.2)
    assert dropper.check().is_stale is True


# Profile self-consistency
def test_profile_loads_and_validates(profile):
    assert profile.validate() == []
    assert profile.fps_limit("object_detection") is not None
    assert 5 <= profile.fps_limit("object_detection") <= 10
    assert profile.data_writes.get("batched") is True
    assert profile.data_writes.get("non_blocking") is True
