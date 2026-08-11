# Duplicate Pipeline Audit

Edge AI Runtime brief, Phase 1, rule 7 ("do not create duplicate camera,
mic, lidar, database, dashboard, or safety pipelines"). This audit exists
specifically to stop Phase 2 (`bonbon_edge_ai_runtime`) from
reimplementing things that already work. Every entry below names the
existing real implementation(s) a naive from-scratch build would
duplicate.

## Confirmed duplicates that already existed before this brief

| Capability | Duplicates | Status | Evidence |
|---|---|---|---|
| RAG | `bonbon_llm/core/rag_retriever.py` (active, used) vs `bonbon_data_stores/rag/{chroma_store.py,rag_query_engine.py}` (dead, unimported) | Self-documented GAP-5 in `config/models/model_registry.yaml:829` | Confirmed dead by this audit — nothing imports the `bonbon_data_stores` version |
| Object detection | `bonbon_vision.YoloDetector` (direct ultralytics, bypasses runtime selection) vs `bonbon_vision.ObjectDetectorRuntimeAdapter` (correct path, via `bonbon_ai_runtime`) vs `bonbon_perception.YoloPersonDetector`/`hog_person_detector.py` (separate package) | Self-documented GAP-2 | `model_registry.yaml:467,488` |
| Two WebSocket managers | `bonbon_operator_api/websocket/ws_manager.py` (23 channels) vs `bonbon_customer_ui/backend/app/websocket/manager.py` (7 channels) | Intentional — two genuinely separate deployable stacks | `docker-compose.customer-ui.yml` header states they're kept standalone by design |
| Two status/health aggregators | `RobotStatusAggregator` (operator_api) vs `HealthAggregator` (customer_ui) | Same — intentional separation | Both real, both serve different audiences |
| Two ROS2 bridges | `bonbon_operator_api/ros2/ros2_bridge.py` (~897 lines) vs `bonbon_customer_ui/backend/app/robot_bridge/ros2_client.py` (320 lines) | Same — intentional | `robot_bridge/` also has `http_client.py`, `mock_client.py` alternate modes |
| Two kiosk frontends | `bonbon_customer_ui/frontend` (patient-facing hospital kiosk) vs `bonbon_operator_api/frontend` (operator/staff dashboard, gesture/face testbench) | Intentional — different audiences, different backends | Both built and deployed (`bonbon-pi1-dashboard-frontend.service`) |

**Assessment of the intentional group**: the `bonbon_robot_ai` /
`bonbon_customer_ui` split is a deliberate two-stack architecture (robot
operator side vs. hospital patient side), talking only over network APIs,
never sharing a container network. This is not a bug — but it means any
new Edge AI dashboard work belongs in `bonbon_operator_api`'s existing
surface, not a third parallel dashboard, and the Phase 1 audit doc
explicitly calls this out so Phase 12 doesn't create one.

## New duplication risks this brief's literal wording would create

The brief asks for 12 new modules under `bonbon_edge_ai_runtime/`. Real,
working equivalents already exist for 5 of them:

| Brief asks for | Already exists as | Verdict |
|---|---|---|
| `cache_manager.py` (LLM/RAG/TTS/FAQ caching) | `bonbon_llm/core/response_cache.py` (LLM, LRU+TTL, safety-aware key) + `bonbon_speech_ai/tts_router.py`'s `HOSPITAL_PHRASE_CACHE_KEYS` (TTS) + `bonbon_data_stores/vector/embedding_manager.py`'s `lru_cache` (embeddings) | **Extend, don't rebuild.** No RAG-*result* cache exists yet — that part is genuinely new. |
| `resource_guard.py` | `bonbon_safety/core/resource_monitor.py` (CPU/RAM/disk) + `bonbon_perception_efficiency/core/load_shedding_controller.py` (hysteresis FSM, thermal-aware) + `bonbon_llm/core/pi2_llm_guard.py` (LLM-specific CPU/temp/safety-state disable) | **Consolidate as a thin facade**, don't reimplement threshold logic that's already correct and tested |
| `degraded_mode_manager.py` | `bonbon_perception_efficiency/core/degraded_mode_manager.py` + `config/runtime/degraded_mode.yaml` | **Already exists under this exact name.** A second one would be a literal duplicate, not just a near-miss. |
| Three-Pi heartbeat/authority (implied by "board heartbeat" priority-1 scheduling item) | `bonbon_distributed_safety/core/heartbeat_monitor.py` + `bonbon_authority_manager/core/authority_manager.py` | **Do not build a new `bonbon_distributed_monitor` package** — that exact name is referenced in `config/distributed/pi_ui_api.yaml` but was "never actually built as such" per that file's own inline note; confirmed zero hits repo-wide. The live equivalent already exists under the two package names above. |
| ASR VAD-gating / vision FPS-throttling (implied by Phase 9 "event-driven processing") | `bonbon_speech_ai/speech_pipeline.py`'s `vad_confirmed` gate + `bonbon_vision/preprocessing/frame_throttler.py::FrameThrottler` | **Already event-driven.** Phase 9 is a verification pass, not new plumbing, for these two. |

### Genuinely new (no existing equivalent found)

- **`task_router.py`** — confirmed by direct search: no file/class named
  `TaskRouter`/`RequestDispatcher` exists anywhere. Per-modality routers
  exist (ASR router, TTS router, `ModelRuntimeSelector`), but nothing
  routes *across* capability types (rule → cache → RAG → LLM →
  escalation). `pi_human_ai.yaml`'s `resolution_order: [rule_engine,
  rag, llm]` key is declared but read by zero code. This is real,
  needed work.
- **`safety_separation_guard.py`** — see `SAFETY_SEPARATION_AUDIT.md`.
  Five to six independent safety mechanisms exist; no single classifier
  unifies them, and two have opposite fail-safe defaults. This is real,
  needed work, but must consolidate existing gates rather than add a 7th.
- **RAG *result* cache** — the LLM response cache indirectly skips RAG
  on a cache hit, but there's no cache internal to the retriever itself.
- **`accelerator_manager.py`** — `bonbon_ai_runtime` already implements
  most of this (Hailo/CPU/mock selection, `HailoDeviceDetector`), but the
  brief's OAK-D-as-camera-source angle and the unified
  `VisionRuntimeInterface` abstraction spanning object/person/gesture
  detection in one place is not fully consolidated today — worth a thin
  new module that wraps `bonbon_ai_runtime` rather than a parallel one.

## Duplicate LLM-safety-authorization finding (spills into this doc from the safety audit)

Two independent authorizers exist in the LLM's actual dispatch path with
**opposite fail-safe defaults** — `bonbon_llm/safety/authorization.py`'s
`CommandAuthorizer` (fail-open) and `bonbon_motion_approval_gateway`
(fail-closed, but disconnected from execution). This is simultaneously a
duplicate-pipeline problem and a safety problem — see
`SAFETY_SEPARATION_AUDIT.md` Findings 1-2 for the full trace.

## Recommendation carried into Phase 2

`bonbon_edge_ai_runtime` should be built as an **orchestration layer**:
- `task_router.py`, `safety_separation_guard.py` (consolidating existing
  gates) — genuinely new code.
- `cache_manager.py`, `resource_guard.py`, `accelerator_manager.py` —
  thin facades that delegate to the real existing implementations named
  above, adding only the cross-cutting pieces that don't exist yet (RAG
  result caching, a unified vision-capability interface).
- `degraded_mode_manager.py` as asked — **do not create**; wire into
  the existing `bonbon_perception_efficiency` one instead, or rename the
  brief's ask to `degraded_mode_bridge.py` if a package-boundary reason
  requires a thin adapter in the new package.
