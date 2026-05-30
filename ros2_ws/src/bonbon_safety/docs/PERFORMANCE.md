# BonBon Performance & Real-Time Engineering

Edge-device (Jetson / RPi-class) performance guide: bottleneck analysis,
optimization plan, latency budgets, and how to measure them. The measurement
layer lives in `bonbon_safety/core/perf_monitor.py`, `perf_targets.py`, and
`resource_monitor.py`; the cross-cutting benchmark is
`tests/benchmarks/bench_hotpaths.py`.

---

## 1. Bottleneck report

Profiled conceptually per stage. The key finding, confirmed by
`bench_hotpaths.py`: **the decision/validation logic is never the bottleneck**
(microseconds against millisecond budgets). Cost lives in **ML inference,
audio/LLM I/O, and serialization**.

| # | Stage | Dominant cost | Bottleneck class | Mitigation (see §2) |
|---|---|---|---|---|
| 1 | camera frame processing | copy + CLAHE/resize per frame | CPU/mem bandwidth | frame sampling, resize, drop-stale |
| 2 | YOLO inference | GPU/CPU forward pass (10–60 ms) | **compute** | warmup, async, ROI, smaller model |
| 3 | face recognition | embedding extract + match | compute | run only on confirmed tracks, cache embeddings |
| 4 | face emotion | DeepFace forward pass | compute | throttle (≤2 Hz), mock fallback |
| 5 | gesture recognition | MediaPipe Holistic (heavy) | **compute** | frame_sample_rate, max_persons, ROI |
| 6 | speech recognition | Whisper decode (100s ms) | **compute** | VAD-first, chunked, timeout, background thread |
| 7 | voice emotion | SpeechBrain forward pass | compute | run per-utterance not per-chunk |
| 8 | LLM response | model decode (100s ms–s) | **compute/IO** | prompt compression, context cap, cache, local 3B model, timeout+fallback |
| 9 | RAG retrieval | vector search + embed | IO/compute | top-k cap, embedding cache, relevance gate |
| 10 | TTS generation | Piper synth (50–150 ms) | compute | precomputed filler audio, emergency phrase cache |
| 11 | spatial reasoning | O(n) geometry (µs) | trivial | none needed (measured ≪ budget) |
| 12 | behavior decision | pattern match (µs) | trivial | none needed (measured ≪ budget) |
| 13 | navigation replanning | Nav2 planner (10s–100s ms) | compute | costmap update rate, planner patience, cache |
| 14 | actuation command | servo bus write + validate (µs) | IO-bound on bus | precomputed primitives, command queue |
| 15 | database writes | SQLite fsync | **IO** | WAL mode, batched/async writes, indices |
| 16 | dashboard WS updates | JSON serialize + socket | IO/CPU | throttle, diff-based, drop high-freq raw |
| 17 | ROS2 serialization | CDR encode + DDS | CPU/network | QoS tuning, BEST_EFFORT for sensors, message size |

Measured hot-path decision latency (`python tests/benchmarks/bench_hotpaths.py`,
2000 reps, dev laptop — robot will differ but ordering holds):

| Hot path | p50 | p95 | p99 | budget | status |
|---|---|---|---|---|---|
| safety_validation | ~0.006 ms | ~0.011 ms | ~0.02 ms | 50 ms | ✅ ≫ margin |
| emergency_stop_reaction | ~0.065 ms | ~0.14 ms | ~0.24 ms | 300 ms | ✅ |
| behavior_decision | ~0.03 ms | ~0.09 ms | ~0.14 ms | 100 ms | ✅ |
| actuation_validation | ~0.002 ms | ~0.002 ms | ~0.003 ms | 50 ms | ✅ |
| gesture_event (classify) | ~0.004 ms | ~0.006 ms | ~0.007 ms | 150 ms | ✅ |
| spatial_reasoning_update | ~0.07 ms | ~0.13 ms | ~0.15 ms | 100 ms | ✅ |

> Interpretation: the software pipeline leaves the **entire** millisecond budget
> for ML inference + I/O. Optimization effort therefore belongs at the model and
> I/O layers, not the decision logic.

---

## 2. Optimization plan & status

Legend: ✅ implemented · 🔧 partial / framework-ready · 📋 recommended.

### Vision
- ✅ frame sampling — `bonbon_vision` `FrameThrottler` (detection_rate_hz)
- ✅ resize / quality gate — `FrameProcessor`
- ✅ async inference + timeout — `BaseDetector` ThreadPoolExecutor + `inference_timeout_sec`
- ✅ drop stale frames — single-slot image buffer under lock
- 🔧 ROI processing — run face/emotion only on confirmed person boxes
- 📋 model warmup at activate (one dummy forward pass)

### Speech
- ✅ VAD-first — Silero VAD gates Whisper
- ✅ chunked audio + background processing — worker thread
- ✅ inference timeout + mock fallback
- ✅ avoid duplicate mic reads — single HAL `microphone_node` owns the device

### LLM / RAG
- ✅ timeout + static fallback — `bonbon_llm` orchestrator
- ✅ retrieved-context limit + relevance gate — RAG retriever top-k
- 🔧 prompt compression — system prompt trimming
- 📋 answer cache for common FAQs (keyed by normalized intent)
- 📋 local lightweight model option (llama3.2:3b already default)

### Data
- ✅ WAL mode + busy_timeout — `bonbon_data_stores` SQLite connection
- ✅ connection reuse — repository pattern holds one connection
- ✅ retention cleanup — `retention_manager`
- 🔧 batched / async logging — queue writes off the hot path
- 📋 index review on hot query columns

### ROS2
- ✅ QoS tuning — BEST_EFFORT/volatile for sensors, RELIABLE/TRANSIENT_LOCAL for state
- ✅ lifecycle nodes — all AI/safety nodes
- ✅ avoid blocking callbacks — heavy work in ThreadPoolExecutor/worker threads
- ✅ health watchdogs — `Watchdog` (perf_monitor sibling) + per-node ModuleHealth
- 🔧 separate callback groups — MutuallyExclusive for timers vs subs where needed

### Actuation
- ✅ precomputed motion primitives — `GestureLibrary` keyframes
- ✅ command queue priority — `MotionQueue`
- ✅ timeout / interruptibility guards — gesture timeout + cancel flag
- 🔧 smooth trajectory generation — velocity-scaled keyframes (acceleration profile 📋)

### Dashboard
- 🔧 throttled WS updates — aggregator publishes at fixed rate
- 📋 diff-based status updates — send only changed fields
- ✅ no high-frequency raw data — only summarized status/telemetry

---

## 3. Measurable targets

Defined once in `bonbon_safety/core/perf_targets.py` (enforced by
`tests/test_perf_targets.py`). `safety_validation`, `actuation_validation`,
`emergency_stop_reaction`, and `tts_emergency` are **critical** budgets.

| Path | Budget | Metric |
|---|---|---|
| behavior_decision | 100 ms | p95 |
| safety_validation | 50 ms | p95 (critical) |
| actuation_validation | 50 ms | p95 (critical) |
| gesture_event | 150 ms | p95 |
| spatial_reasoning_update | 100 ms | p95 |
| emergency_stop_reaction | 300 ms | p99 (critical) |
| dashboard_status | 100 ms | p95 |
| database_write | 100 ms | p95 |
| rag_query | 500 ms | p95 |
| tts_emergency | 500 ms | p99 (critical) |

---

## 4. How to measure

### Cross-cutting hot-path benchmark
```bash
cd ros2_ws/src/bonbon_safety
python tests/benchmarks/bench_hotpaths.py          # table
python tests/benchmarks/bench_hotpaths.py --json   # machine-readable
python -m pytest tests/benchmarks/bench_hotpaths.py -q   # latency tests vs budget
```

### Per-package ML/IO benchmarks (real stages, mock weights)
```bash
python -m pytest ros2_ws/src/bonbon_vision/tests/benchmarks/bench_inference.py -s
python -m pytest ros2_ws/src/bonbon_speech/tests/benchmarks/bench_speech.py -s
python -m pytest ros2_ws/src/bonbon_llm/tests/benchmarks/bench_llm.py -s
python -m pytest ros2_ws/src/bonbon_perception_ai/tests/benchmarks/bench_perception.py -s
```

### Runtime budget enforcement (in a node)
```python
from bonbon_safety.core.perf_monitor import LatencyTracker, LatencyTimer, check_budget
from bonbon_safety.core.perf_targets import build_targets

tracker = LatencyTracker("behavior_decision")
budgets = build_targets()
with LatencyTimer(tracker):
    decision = engine.decide(...)
report = check_budget(tracker, budgets["behavior_decision"])  # logs if exceeded
```

### Resource monitoring (load shedding)
```python
from bonbon_safety.core.resource_monitor import ResourceMonitor
mon = ResourceMonitor(data_path="/var/bonbon/data")
snap = mon.sample()                 # cpu/mem/disk, psutil-optional
rate_scale = mon.recommended_load_shed()   # 1.0 normal … 0.5 under load
# multiply inference/publish rates by rate_scale when under pressure
```

---

## 5. Reuse / extend

- **Add a new budget**: add a `PerfBudget` to `perf_targets.py`; `test_perf_targets.py`
  guards the required set.
- **Instrument a node**: wrap the hot path with `LatencyTimer` into a
  `LatencyTracker`, publish `stats()` into `ModuleHealth.latency_ms`, and call
  `check_budget` on a timer — a breach can raise a fault via the
  `FaultHandler` (`SYS_CPU_OVERLOAD` / dedicated perf fault).
- **Load shedding**: feed `ResourceMonitor.recommended_load_shed()` into timer
  periods (System failures 41/42 in `FAILURE_MODES.md`).
