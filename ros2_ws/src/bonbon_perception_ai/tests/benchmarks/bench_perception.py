"""
bonbon_perception_ai latency benchmarks
=======================================
Measures wall-clock latency for every pipeline stage using pure-Python mocks.
No ROS2, no GPU, no external API required.

Usage
-----
    pytest tests/benchmarks/bench_perception.py -s -v    # pytest with p99 budgets
    python tests/benchmarks/bench_perception.py           # table output (200 reps)
    python tests/benchmarks/bench_perception.py --quick   # 50 reps
    python tests/benchmarks/bench_perception.py --json    # JSON output
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Callable
from statistics import mean, median

import pytest
from bonbon_perception_ai.config.perception_config import (
    FusionConfig,
    IntentConfig,
    MemoryConfig,
    RiskConfig,
    SceneConfig,
)
from bonbon_perception_ai.fusion.multimodal_fusion import MultimodalFusion
from bonbon_perception_ai.fusion.types import (
    ObjectObservation,
    PersonObservation,
    SpeechInput,
)
from bonbon_perception_ai.memory.memory_manager import MemoryManager
from bonbon_perception_ai.memory.vector_store import SceneEmbedding
from bonbon_perception_ai.understanding.behavior_recommender import BehaviorRecommender
from bonbon_perception_ai.understanding.intent_engine import IntentEngine
from bonbon_perception_ai.understanding.risk_assessor import RiskAssessor
from bonbon_perception_ai.understanding.scene_analyzer import SceneAnalyzer, SceneSnapshot

# ── Harness ───────────────────────────────────────────────────────────────────


class BenchResult:
    def __init__(self, name: str, reps: int, samples_ms: list[float]) -> None:
        self.name = name
        self.reps = reps
        self.samples_ms = sorted(samples_ms)

    def mean_ms(self) -> float:
        return mean(self.samples_ms)

    def p50_ms(self) -> float:
        return median(self.samples_ms)

    def min_ms(self) -> float:
        return self.samples_ms[0]

    def max_ms(self) -> float:
        return self.samples_ms[-1]

    def p95_ms(self) -> float:
        return _pct(self.samples_ms, 95)

    def p99_ms(self) -> float:
        return _pct(self.samples_ms, 99)

    def to_dict(self) -> dict:
        return {
            "bench": self.name,
            "reps": self.reps,
            "mean_ms": round(self.mean_ms(), 3),
            "p50_ms": round(self.p50_ms(), 3),
            "p95_ms": round(self.p95_ms(), 3),
            "p99_ms": round(self.p99_ms(), 3),
            "min_ms": round(self.min_ms(), 3),
            "max_ms": round(self.max_ms(), 3),
        }


def _pct(s: list[float], pct: int) -> float:
    n = len(s)
    if n == 1:
        return s[0]
    i = pct / 100 * (n - 1)
    lo, hi = int(i), min(int(i) + 1, n - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _bench(name: str, fn: Callable, reps: int, warmup: int = 3) -> BenchResult:
    for _ in range(warmup):
        fn()
    t_ms: list[float] = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        t_ms.append((time.perf_counter() - t0) * 1000.0)
    return BenchResult(name, reps, t_ms)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _fresh_cfg() -> FusionConfig:
    return FusionConfig(
        objects_stale_sec=60.0,
        persons_stale_sec=60.0,
        speech_stale_sec=60.0,
        pose_stale_sec=60.0,
        nav_stale_sec=60.0,
    )


def _snap(activity="idle") -> SceneSnapshot:
    return SceneSnapshot(
        scene_id=str(uuid.uuid4()),
        timestamp=time.monotonic(),
        confidence=0.9,
        uncertainty_level="LOW",
        present_object_classes=["cup"],
        present_person_ids=["p1"],
        dominant_activity=activity,
        activity_label=activity,
        spatial_context="near_person",
        human_proximity_m=1.5,
        is_crowded=False,
        stale_modalities=[],
        description="bench",
    )


def _ctx_with_person():
    f = MultimodalFusion(_fresh_cfg())
    f.update_persons([PersonObservation("p1", confidence=0.9, distance_m=1.5)])
    f.update_objects([ObjectObservation("cup", confidence=0.9, distance_m=1.5)])
    f.update_speech(SpeechInput(text="order coffee", confidence=0.9))
    return f.fuse()


# ── Individual benchmarks ─────────────────────────────────────────────────────


def bench_fusion_fuse(reps: int) -> BenchResult:
    """MultimodalFusion.fuse() with 3 active modalities."""
    f = MultimodalFusion(_fresh_cfg())
    f.update_persons([PersonObservation("p1", 0.9, distance_m=1.5)])
    f.update_objects([ObjectObservation("cup", 0.9)])
    f.update_speech(SpeechInput("hello", 0.9))
    return _bench("fusion_fuse", f.fuse, reps)


def bench_modality_update(reps: int) -> BenchResult:
    """update_objects() with 5 objects."""
    f = MultimodalFusion(_fresh_cfg())
    objs = [ObjectObservation(f"obj{i}", 0.9) for i in range(5)]
    return _bench("fusion_update_objects", lambda: f.update_objects(objs), reps)


def bench_scene_analyze_idle(reps: int) -> BenchResult:
    """SceneAnalyzer.analyze() — idle scene (no persons)."""
    an = SceneAnalyzer(SceneConfig())
    f = MultimodalFusion(_fresh_cfg())
    return _bench("scene_analyze_idle", lambda: an.analyze(f.fuse()), reps)


def bench_scene_analyze_with_persons(reps: int) -> BenchResult:
    """SceneAnalyzer.analyze() — 3 persons, generating events."""
    an = SceneAnalyzer(SceneConfig(event_debounce_sec=0.0))
    f = MultimodalFusion(_fresh_cfg())
    persons = [PersonObservation(f"p{i}", 0.9, distance_m=1.0 + i * 0.5) for i in range(3)]
    f.update_persons(persons)
    return _bench("scene_analyze_3persons", lambda: an.analyze(f.fuse()), reps)


def bench_intent_classify_match(reps: int) -> BenchResult:
    """IntentEngine.classify() — clear order_item intent."""
    eng = IntentEngine(IntentConfig())
    sp = SpeechInput("I'd like to order a coffee please", confidence=0.9)
    ctx = _ctx_with_person()
    return _bench("intent_classify_match", lambda: eng.classify(sp, ctx), reps)


def bench_intent_classify_ambiguous(reps: int) -> BenchResult:
    """IntentEngine.classify() — no-match / ambiguous."""
    eng = IntentEngine(IntentConfig(ambiguity_policy="clarify"))
    sp = SpeechInput("xyzzy plugh blerp", confidence=0.9)
    ctx = _ctx_with_person()
    return _bench("intent_classify_ambiguous", lambda: eng.classify(sp, ctx), reps)


def bench_risk_assess_no_risk(reps: int) -> BenchResult:
    """RiskAssessor.assess() — no risks (far persons, stable nav)."""
    ra = RiskAssessor(RiskConfig())
    f = MultimodalFusion(_fresh_cfg())
    f.update_persons([PersonObservation("p1", 0.9, distance_m=3.0)])
    snap = _snap()

    def _run():
        ctx = f.fuse()
        ra.assess(ctx, snap)

    return _bench("risk_assess_no_risk", _run, reps)


def bench_risk_assess_critical(reps: int) -> BenchResult:
    """RiskAssessor.assess() — critical proximity risk."""
    ra = RiskAssessor(RiskConfig())
    f = MultimodalFusion(_fresh_cfg())
    f.update_persons([PersonObservation("p1", 0.9, distance_m=0.25)])
    snap = _snap()

    def _run():
        ctx = f.fuse()
        ra.assess(ctx, snap)

    return _bench("risk_assess_critical", _run, reps)


def bench_behavior_recommend(reps: int) -> BenchResult:
    """BehaviorRecommender.recommend() — intent-driven."""
    from bonbon_perception_ai.understanding.intent_engine import IntentSlot, UserIntent

    br = BehaviorRecommender()
    intent = UserIntent(
        intent_class="order_item",
        confidence=0.9,
        speaker_id="u1",
        raw_text="coffee",
        slots=[IntentSlot("item", "coffee", 0.9)],
    )
    ctx = _ctx_with_person()
    snap = _snap("interacting")

    def _run():
        br.recommend(ctx, snap, intent, [])

    return _bench("behavior_recommend", _run, reps)


def bench_scene_embedding(reps: int) -> BenchResult:
    """SceneEmbedding.encode() + normalise()."""
    snap = _snap()

    def _run():
        v = SceneEmbedding.encode(snap)
        SceneEmbedding.normalise(v)

    return _bench("scene_embedding", _run, reps)


def bench_memory_record_scene(reps: int) -> BenchResult:
    """MemoryManager.record_scene() — in-memory SQLite + NumPy."""
    m = MemoryManager(MemoryConfig(db_path=""))
    m.open()

    def _run():
        m.record_scene(_snap())

    result = _bench("memory_record_scene", _run, reps, warmup=1)
    m.close()
    return result


def bench_memory_recall(reps: int) -> BenchResult:
    """MemoryManager.recall_similar_scenes() over 200 stored episodes."""
    m = MemoryManager(MemoryConfig(db_path="", max_episodes=500))
    m.open()
    for i in range(200):
        activities = ["idle", "interacting", "navigating", "serving"]
        m.record_scene(_snap(activities[i % len(activities)]))
    query = _snap("interacting")

    def _run():
        m.recall_similar_scenes(query, k=5)

    result = _bench("memory_recall_200ep", _run, reps, warmup=1)
    m.close()
    return result


def bench_end_to_end(reps: int) -> BenchResult:
    """Full pipeline: fuse → analyze → intent → risk → behavior."""
    f = MultimodalFusion(_fresh_cfg())
    an = SceneAnalyzer(SceneConfig(event_debounce_sec=0.0))
    eng = IntentEngine(IntentConfig())
    ra = RiskAssessor(RiskConfig())
    br = BehaviorRecommender()
    speech = SpeechInput("please bring me a coffee", confidence=0.9)

    f.update_persons([PersonObservation("p1", 0.9, distance_m=1.5)])
    f.update_objects([ObjectObservation("cup", 0.9)])
    f.update_speech(speech)

    def _pipeline():
        ctx = f.fuse()
        snap, events = an.analyze(ctx)
        intent = eng.classify(speech, ctx)
        risks = ra.assess(ctx, snap, intent.intent_class if intent else None)
        br.recommend(ctx, snap, intent, risks)

    return _bench("e2e_pipeline", _pipeline, reps)


# ── All benchmarks ────────────────────────────────────────────────────────────

_ALL = [
    bench_fusion_fuse,
    bench_modality_update,
    bench_scene_analyze_idle,
    bench_scene_analyze_with_persons,
    bench_intent_classify_match,
    bench_intent_classify_ambiguous,
    bench_risk_assess_no_risk,
    bench_risk_assess_critical,
    bench_behavior_recommend,
    bench_scene_embedding,
    bench_memory_record_scene,
    bench_memory_recall,
    bench_end_to_end,
]


def run_all(reps: int = 200) -> list[BenchResult]:
    return [fn(reps) for fn in _ALL]


def _print_table(results: list[BenchResult]) -> None:
    cols = ["bench", "reps", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms"]
    rows = [r.to_dict() for r in results]
    widths = {c: max(len(c), max(len(str(row[c])) for row in rows)) for c in cols}
    sep = "  ".join("-" * widths[c] for c in cols)
    hdr = "  ".join(c.ljust(widths[c]) for c in cols)
    print(f"\n{hdr}\n{sep}")
    for row in rows:
        print("  ".join(str(row[c]).ljust(widths[c]) for c in cols))
    print()


# ── pytest integration ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bench_fn,max_p99_ms",
    [
        (bench_fusion_fuse, 1.0),
        (bench_modality_update, 0.5),
        (bench_scene_analyze_idle, 2.0),
        (bench_scene_analyze_with_persons, 5.0),
        (bench_intent_classify_match, 2.0),
        (bench_intent_classify_ambiguous, 2.0),
        (bench_risk_assess_no_risk, 1.0),
        (bench_risk_assess_critical, 1.0),
        (bench_behavior_recommend, 1.0),
        (bench_scene_embedding, 0.5),
        (bench_memory_record_scene, 10.0),
        (bench_memory_recall, 15.0),
        (bench_end_to_end, 10.0),
    ],
)
def test_bench_latency(bench_fn, max_p99_ms):
    result = bench_fn(50)
    print(f"\n  {result.name}: p99={result.p99_ms():.3f} ms  (budget={max_p99_ms} ms)")
    assert (
        result.p99_ms() <= max_p99_ms
    ), f"{result.name} p99={result.p99_ms():.3f} ms exceeds {max_p99_ms} ms"


# ── CLI ───────────────────────────────────────────────────────────────────────


def _cli() -> None:
    parser = argparse.ArgumentParser(description="bonbon_perception_ai benchmarks")
    parser.add_argument("--quick", action="store_true", help="50 reps")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    results = run_all(50 if args.quick else 200)
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        _print_table(results)


if __name__ == "__main__":
    _cli()
