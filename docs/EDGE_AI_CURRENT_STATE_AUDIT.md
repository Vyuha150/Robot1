# Edge AI Current-State Audit

Edge AI Runtime brief, Phase 1. All 25 requested areas, each reporting
the 9 required fields. No code was modified to produce this document.
Companion docs: `EDGE_AI_GAP_ANALYSIS.md` (prioritized fixes),
`DUPLICATE_PIPELINE_AUDIT.md` (duplication detail),
`SAFETY_SEPARATION_AUDIT.md` (safety detail, the most important of the
four), `THREE_PI_RUNTIME_AUDIT.md` (board allocation detail).

Status legend: WORKING / PARTIAL / MISSING / MOCK_ONLY / BLOCKED / UNSAFE.

---

### 1. UI/customer interaction module
- **Status**: WORKING (two separate UIs — see duplicate risk)
- **Runtime**: UI Pi (`bonbon_operator_api/frontend`) + separate `bonbon_customer_ui/frontend` repo
- **Model used**: n/a (frontend)
- **Fallback**: `degraded.tsx` route exists in customer UI for offline/degraded states
- **Dashboard visible**: is itself the dashboard (operator side) / the patient kiosk (customer side)
- **Safety risk**: none found — no direct hardware topic references from either UI package
- **Efficiency risk**: low
- **Duplicate pipeline risk**: **two separate kiosk frontends** on two separate backends, by design (see `DUPLICATE_PIPELINE_AUDIT.md`)
- **Exact fix needed**: none required by this brief; Phase 12 dashboard work belongs in `bonbon_operator_api`'s existing frontend, not a new one

### 2. Backend/API layer
- **Status**: WORKING
- **Runtime**: UI Pi (`bonbon_operator_api`, FastAPI)
- **Model used**: n/a
- **Fallback**: n/a
- **Dashboard visible**: is the API — 84 REST endpoints across 13 routers, 23 WebSocket channels
- **Safety risk**: none — no direct actuation endpoints found
- **Efficiency risk**: none found
- **Duplicate pipeline risk**: `bonbon_customer_ui` has its own separate backend (intentional split)
- **Exact fix needed**: none; Phase 12 extends this existing surface with edge-ai endpoints/channels

### 3. ROS2 bridge
- **Status**: WORKING
- **Runtime**: UI Pi (`bonbon_operator_api/ros2/ros2_bridge.py`)
- **Model used**: n/a
- **Fallback**: honest `NOT_IMPLEMENTED` responses for unbacked commands (`emergency_stop`, `pause`, `resume`, `restart_module`, `get_config`, `set_config`, `memory_query`, `rag_query`) rather than fake success
- **Dashboard visible**: yes, feeds most of the dashboard's live state
- **Safety risk**: none in the bridge itself (read-mostly; the one write path — `/bonbon/tts/request`, `/bonbon/operator/proposal` — is a proposal, not a direct command)
- **Efficiency risk**: none found
- **Duplicate pipeline risk**: `bonbon_customer_ui` has its own separate ROS2 bridge (`robot_bridge/ros2_client.py`, intentional split)
- **Exact fix needed**: none

### 4. AI interaction stack (cross-cutting)
- **Status**: PARTIAL
- **Runtime**: AI Pi (per `pi_human_ai.yaml`)
- **Model used**: see rows 7-16 individually
- **Fallback**: yes, per-capability chains all resolve to an honest terminal fallback
- **Dashboard visible**: yes, `/ai-models/*`, `/speech-ai/*`, `/llm-local/*`, `/perception-ai/*`, `/affective-ai/*`, `/gesture-ai/*`
- **Safety risk**: **the LLM's behavior-proposal dispatch path is the GAP-E1 finding** — see row 7 and `SAFETY_SEPARATION_AUDIT.md`
- **Efficiency risk**: no cross-capability router exists (GAP-E8) — every request that could be a cheap deterministic/cached answer still has to be explicitly coded per-caller to check that first, nothing enforces "cheapest safe route" systemically
- **Duplicate pipeline risk**: see GAP-E7, E9, E10
- **Exact fix needed**: Phase 4 task router + Phase 7 safety separation guard

### 5. Navigation stack
- **Status**: PARTIAL / UNSAFE (goal dispatch path)
- **Runtime**: Navigation Pi (`bonbon_navigation`)
- **Model used**: n/a (Nav2/SLAM, not ML in the AI-model sense)
- **Fallback**: n/a
- **Dashboard visible**: yes, navigation status/goal state
- **Safety risk**: **UNSAFE** — Nav2 goal dispatch (`_on_behavior_recommendation` → `BasicNavigator.goToPose()`) is gated only by a fail-open `CommandAuthorizer`, not `bonbon_motion_approval_gateway`. Wheel-velocity gating is dead code (never wired), so velocity currently cannot reach motors at all (broken, not gated). See `SAFETY_SEPARATION_AUDIT.md` Findings 1, 5.
- **Efficiency risk**: none found beyond the above
- **Duplicate pipeline risk**: `SafetyStopBridge` is a third independent velocity gate alongside `safety_gate_node` and `bonbon_motion_approval_gateway`
- **Exact fix needed**: Phase 7, GAP-E1/E3

### 6. Safety supervisor
- **Status**: WORKING (the supervisor + gate themselves) / PARTIAL (as the *sole* authority — it isn't yet)
- **Runtime**: Navigation Pi (`bonbon_safety`)
- **Model used**: n/a
- **Fallback**: fail-closed watchdog in `safety_gate_node` (blocks after 2s of no supervisor heartbeat) — solid
- **Dashboard visible**: yes, `/bonbon/safety/state`
- **Safety risk**: the supervisor/gate pair is correctly enforced for servo/stepper actuation (confirmed no bypass), but is bypassed entirely for Nav2 goal dispatch (row 5) — so "Safety Supervisor is the sole authority" (this brief's rule 6) is true for one actuation path and false for another
- **Efficiency risk**: none found
- **Duplicate pipeline risk**: see GAP-E5 — 5-6 independent safety mechanisms exist instead of one
- **Exact fix needed**: Phase 7 must make the gateway's decision authoritative for navigation dispatch, not just actuation

### 7. Local LLM / Ollama
- **Status**: WORKING (inference) / UNSAFE (its downstream dispatch path — see row 5)
- **Runtime**: AI Pi (`bonbon_llm`)
- **Model used**: `qwen2.5:0.5b` via Ollama (registered primary, benchmarked on real Pi-2 2026-07-06); `llama3.2:1b`/`qwen2.5:1.5b` benchmark-only, never auto-enabled
- **Fallback**: static template fallback on error/timeout/hallucination; no cloud fallback (`cloud_api_fallback: false`, explicitly forbidden)
- **Dashboard visible**: yes, `/llm-local/status`
- **Safety risk**: **UNSAFE downstream** — see row 5/GAP-E1. The LLM node itself has no actuation-authority fields (verified by existing test), the risk is entirely in what happens after it publishes a `BehaviorRecommendation`.
- **Efficiency risk**: `resolution_order: [rule_engine, rag, llm]` declared in config but enforced by zero code (GAP-E8) — LLM may be invoked in cases a rule/cache could have answered
- **Duplicate pipeline risk**: `langchain_bridge.py` vs direct `OllamaClient` — not a true duplicate (LangChain tried first, silent fallback to direct client)
- **Exact fix needed**: Phase 4 (enforce resolution order), Phase 7 (fix downstream dispatch)

### 8. RAG
- **Status**: PARTIAL
- **Runtime**: AI Pi (`bonbon_llm/core/rag_retriever.py`)
- **Model used**: ChromaDB → FAISS → NumPy backend chain, sentence-transformers or hash-embedding fallback, small hardcoded knowledge base
- **Fallback**: yes, 3-tier chain always resolves
- **Dashboard visible**: bundled into `/llm-local/status`
- **Safety risk**: none
- **Efficiency risk**: no RAG-specific result cache (GAP-E11); retrieval is skipped only indirectly via the LLM response cache
- **Duplicate pipeline risk**: **confirmed dead duplicate** — `bonbon_data_stores/rag/{chroma_store.py,rag_query_engine.py}` is unimported (GAP-E9, pre-existing GAP-5)
- **Exact fix needed**: Phase 6 adds a result cache; separately, delete or clearly deprecate the dead `bonbon_data_stores` RAG code

### 9. ASR
- **Status**: WORKING
- **Runtime**: AI Pi (`bonbon_speech_ai/asr_router.py`, wrapping `bonbon_speech`)
- **Model used**: `asr_faster_whisper` (base) real default; Sarvam Edge gated behind access detection; sherpa-onnx/whisper.cpp registered, not wired
- **Fallback**: full chain to `asr_degraded_template` (typed/touch input), never crashes
- **Dashboard visible**: yes, `/speech-ai/asr`
- **Safety risk**: none
- **Efficiency risk**: none new found (already event-driven, see row 19); known separate finding from an earlier pass — no model-instance caching across calls (flagged, tracked as a separate follow-up task, not part of this brief's scope unless Phase 6 chooses to fold it in)
- **Duplicate pipeline risk**: none — `asr_router.py` explicitly wraps, not reimplements, `bonbon_speech`'s VAD/wake-word
- **Exact fix needed**: none required by this brief

### 10. TTS
- **Status**: WORKING
- **Runtime**: AI Pi (`bonbon_speech_ai/tts_router.py`, wrapping `bonbon_tts`)
- **Model used**: Piper `en_US-lessac-medium`, verified on real Pi-2; Hindi voice registered but not fetched (GAP-8, pre-existing)
- **Fallback**: any synthesis exception caught, degrades to `tts_text_only`, never blocks
- **Dashboard visible**: yes, `/speech-ai/tts`
- **Safety risk**: none — code explicitly documents "TTS must not block safety"
- **Efficiency risk**: same model-instance-caching note as row 9
- **Duplicate pipeline risk**: none — same wrap-not-reimplement pattern as ASR
- **Exact fix needed**: none required by this brief

### 11. Object detection
- **Status**: PARTIAL (BLOCKED on hardware for the Hailo tier)
- **Runtime**: AI Pi (`bonbon_vision`)
- **Model used**: Hailo YOLO (primary, HARDWARE_BLOCKED — no `.hef`, no device detected as of 2026-07-06) → CPU ONNX via runtime adapter → direct Ultralytics YOLOv8n → mock
- **Fallback**: yes, full chain to `vision_mock`
- **Dashboard visible**: via `/ai-models/status`, `/perception-ai/status` (no dedicated endpoint)
- **Safety risk**: none
- **Efficiency risk**: FPS-limited via `FrameThrottler` + `max_fps_pi: 10` — already handled
- **Duplicate pipeline risk**: **confirmed, pre-existing GAP-2/GAP-E10** — `bonbon_vision.YoloDetector` (direct) vs `ObjectDetectorRuntimeAdapter` (correct path) vs `bonbon_perception`'s separate detectors; also `vision_ultralytics_direct` has an unresolved AGPL-3.0/`commercial_allowed:unknown` license flag
- **Exact fix needed**: Phase 5 accelerator manager should standardize on `ObjectDetectorRuntimeAdapter`; license flag needs a product decision, not a code fix

### 12. Person detection
- **Status**: PARTIAL (BLOCKED on hardware for the Hailo tier)
- **Runtime**: AI Pi (`bonbon_perception`)
- **Model used**: `vision_person_hailo_yolo` (HARDWARE_BLOCKED) → fallback → `vision_mock`
- **Fallback**: yes
- **Dashboard visible**: via `/perception-ai/status`
- **Safety risk**: none directly, but see row 16 (human-state fusion depends on this)
- **Efficiency risk**: `max_fps_pi: 12`, already throttled
- **Duplicate pipeline risk**: same GAP-2/GAP-E10 as row 11 — separate package from object detection with its own detector implementations
- **Exact fix needed**: same as row 11

### 13. Face recognition
- **Status**: MOCK_ONLY (by design) / effectively BLOCKED for production use
- **Runtime**: AI Pi (`bonbon_vision/face`, `bonbon_perception/nodes/face_node.py`)
- **Model used**: InsightFace (registered, `commercial_allowed: false` for pretrained weights, disabled by default) / DeepFace (dev-tier, disabled by default) / `face_mock` (real default, always "unknown person")
- **Fallback**: terminal mock, never fabricates identity
- **Dashboard visible**: bundled into `/perception-ai/status`
- **Safety risk**: none (defaults to anonymous)
- **Efficiency risk**: none found
- **Duplicate pipeline risk**: none new found
- **Exact fix needed**: **no enrollment/consent mechanism exists anywhere** (pre-existing GAP-3) — a product/privacy decision, not something this brief's phases fix; face recognition should stay mock-default until that's resolved

### 14. Gesture recognition
- **Status**: PARTIAL
- **Runtime**: AI Pi (`bonbon_gesture`)
- **Model used**: MediaPipe Holistic, real default; 10 of 16 requested gesture classes actually work (documented honestly in the registry — `come_here`/`go_away` wired but never detected, `pointing_at_object`/`namaste` unimplemented)
- **Fallback**: `gesture_mock` (always "unknown")
- **Dashboard visible**: yes, `/gesture-ai/status`
- **Safety risk**: none directly — gesture output only ever becomes a `BehaviorProposal`, never a direct command (confirmed no direct-write path)
- **Efficiency risk**: processes every incoming camera frame continuously — no VAD-equivalent event gate of its own (GAP-E12), relies entirely on upstream vision throttling
- **Duplicate pipeline risk**: none found; package name is `bonbon_gesture`, not `bonbon_gesture_ai` as some docs assume — worth using the real name in Phase 2+
- **Exact fix needed**: Phase 9 should verify whether upstream throttling is sufficient or gesture needs its own gate

### 15. Affective AI
- **Status**: PARTIAL
- **Runtime**: AI Pi (`bonbon_affective_ai`)
- **Model used**: DeepFace (face emotion), SpeechBrain wav2vec2-IEMOCAP (voice emotion), both real defaults per the prior pass's GAP-1 fix
- **Fallback**: `emotion_face_mock` (neutral, zero confidence) / `voice_emotion_text_sentiment` (transcript-derived)
- **Dashboard visible**: yes, `/affective-ai/status`
- **Safety risk**: none — per-person, uncertainty-preserving by design; a 3-level privacy gate (`none`/`face_only`/`suppressed`) exists
- **Efficiency risk**: SpeechBrain's ~1.2GB RAM footprint flagged as a real concern on an 8GB Pi-2 already running LLM+vision+ASR (pre-existing note, re-confirmed); voice emotion correctly scoped to speech segments only, not continuous
- **Duplicate pipeline risk**: none found
- **Exact fix needed**: none required by this brief; RAM budgeting is a Phase 8 resource-guard concern to monitor, not a new bug

### 16. Human-state fusion
- **Status**: WORKING
- **Runtime**: AI Pi (`bonbon_human_state_fusion`)
- **Model used**: n/a — pure fusion logic over other modules' outputs (person tracks, emotion, gesture, speaker turn, intent), bridging 3 different ID spaces
- **Fallback**: inherits upstream fallbacks (no model of its own to fail)
- **Dashboard visible**: not confirmed as a dedicated dashboard route in this pass — consumes `/bonbon/human_state/*` topics, not verified wired to a REST/WS endpoint
- **Safety risk**: none
- **Efficiency risk**: staleness windows already implemented (`_GESTURE_RECENCY_SEC=3.0`, `_EMOTION_RECENCY_SEC=6.0`, `_TEXT_BRIDGE_MAX_AGE_SEC=3.0`)
- **Duplicate pipeline risk**: none found
- **Exact fix needed**: Phase 12 should confirm/add dashboard visibility for this module specifically — it's real and working but not confirmed visible today

### 17. Model runtime selection
- **Status**: WORKING
- **Runtime**: AI Pi (`bonbon_ai_model_registry/model_runtime_selector.py`, delegating vision-specific decisions to `bonbon_ai_runtime/runtime_selector.py`)
- **Model used**: n/a — this is the selector itself
- **Fallback**: `model_fallback_policy.py`'s `FallbackDecision.degraded` flag when a chain is exhausted
- **Dashboard visible**: yes, `model_dashboard_publisher.py` explicitly backs 5 of the existing status endpoints
- **Safety risk**: none
- **Efficiency risk**: none found — real availability checks (`importlib.util.find_spec`, `shutil.which`, env vars), not guessed
- **Duplicate pipeline risk**: two layers (cross-capability `ModelRuntimeSelector` + vision-specific `RuntimeSelector`) but explicitly delegating, not duplicating
- **Exact fix needed**: none required by this brief; Phase 5's `accelerator_manager.py` should be a thin wrapper adding OAK-D-as-source and a unified vision interface, not a third selector

### 18. Hailo / AI HAT runtime
- **Status**: BLOCKED (hardware)
- **Runtime**: AI Pi (`bonbon_ai_runtime/hailo_device_detector.py`)
- **Model used**: n/a — detection code, real and testable (`hailortcli scan` / `lspci` fallback + `importlib.util.find_spec("hailort")`)
- **Fallback**: CPU/mock, already wired
- **Dashboard visible**: yes, via `/ai-runtime/status`
- **Safety risk**: none
- **Efficiency risk**: none — detection is a synchronous check, not a hot path
- **Duplicate pipeline risk**: none found
- **Exact fix needed**: none code-side; genuinely hardware-blocked — no `.hef` file exists anywhere in the repo and no device was detected as of the last real hardware check (2026-07-06)

### 19. Caching
- **Status**: PARTIAL
- **Runtime**: AI Pi (mostly)
- **Model used**: n/a
- **Fallback**: n/a
- **Dashboard visible**: not confirmed — cache hit/miss metrics are not currently surfaced on any dashboard endpoint found
- **Safety risk**: none
- **Efficiency risk**: real caches exist (LLM response cache, TTS phrase cache, embedding LRU cache) but no RAG result cache (GAP-E11) and no unified cache-hit metrics visibility (rule 10/Phase 6 requirement)
- **Duplicate pipeline risk**: **high if built naively** — see GAP-E7/`DUPLICATE_PIPELINE_AUDIT.md`
- **Exact fix needed**: Phase 6 should be a metrics/visibility layer over the existing caches plus the new RAG result cache, not a replacement

### 20. Resource guard
- **Status**: WORKING (as scattered pieces) / MISSING (as a unified concept)
- **Runtime**: AI Pi + Navigation Pi (thresholds shared, enforcement per-module)
- **Model used**: n/a
- **Fallback**: n/a
- **Dashboard visible**: not confirmed as a single unified view — individual signals may surface piecemeal
- **Safety risk**: none — thermal/CPU thresholds are consistently mirrored across `bonbon_safety`, `bonbon_perception_efficiency`, `bonbon_llm` (verified, not just claimed)
- **Efficiency risk**: none — `ResourceMonitor`, `LoadSheddingController`, `Pi2LLMGuard` are all real and correctly thresholded
- **Duplicate pipeline risk**: **high if built naively** — see GAP-E7
- **Exact fix needed**: Phase 8 should be a thin facade unifying visibility across the three existing implementations, not a fourth threshold system

### 21. Degraded mode
- **Status**: WORKING
- **Runtime**: AI Pi (`bonbon_perception_efficiency/core/degraded_mode_manager.py`)
- **Model used**: n/a
- **Fallback**: n/a — this IS the fallback mechanism
- **Dashboard visible**: yes, `degraded-mode` WS channel already exists
- **Safety risk**: none — `never_disable:` list correctly protects safety_supervisor/emergency_stop/hal/lidar/navigation_safety/active_person_tracking
- **Efficiency risk**: none found
- **Duplicate pipeline risk**: **the brief literally asks to build this again under the same name** — do not; see GAP-E7
- **Exact fix needed**: none — reuse the existing module

### 22. Dashboard status
- **Status**: WORKING
- **Runtime**: UI Pi (`bonbon_operator_api`)
- **Model used**: n/a
- **Fallback**: honest UNKNOWN/OFFLINE reporting confirmed in multiple places (e.g. deployment-readiness endpoint's own docstring)
- **Safety risk**: none
- **Efficiency risk**: none found
- **Duplicate pipeline risk**: see row 1 — two dashboards by design, don't add a third
- **Exact fix needed**: Phase 12 extends the existing 23-channel/84-endpoint surface with the brief's edge-ai-specific additions

### 23. Tests
- **Status**: PARTIAL
- **Runtime**: n/a
- **Model used**: n/a
- **Fallback**: n/a
- **Dashboard visible**: n/a
- **Safety risk**: **GAP-E6** — no test exercises the real ROS2 topic graph for safety separation; `tests/safety/` is empty
- **Efficiency risk**: n/a
- **Duplicate pipeline risk**: n/a
- **Exact fix needed**: Phase 13's tests must include real-topic-graph safety tests, not just unit-level text/schema checks (which is all that exists today for this specific area)

### 24. Deployment scripts
- **Status**: WORKING
- **Runtime**: n/a
- **Model used**: n/a
- **Fallback**: n/a
- **Dashboard visible**: n/a
- **Safety risk**: none
- **Efficiency risk**: none found
- **Duplicate pipeline risk**: a flat/legacy set of 11 systemd services coexists with the per-Pi split (29 services) — Phase 10's new scripts must target the per-Pi ones
- **Exact fix needed**: none beyond that targeting note

### 25. Systemd services
- **Status**: WORKING
- **Runtime**: all three Pis
- **Model used**: n/a
- **Fallback**: n/a
- **Dashboard visible**: n/a
- **Safety risk**: none
- **Efficiency risk**: none found
- **Duplicate pipeline risk**: see row 24
- **Exact fix needed**: none

---

## Cross-cutting summary

- **1 UNSAFE finding** (row 5/7, GAP-E1) requiring immediate attention in Phase 7.
- **5 areas are PARTIAL due to real hardware/access blockers** (Hailo tier of object/person detection, face recognition licensing) — correctly not faked anywhere.
- **5 modules the brief asks to build "new" already exist and working** (LLM cache, resource monitoring ×3, degraded mode, three-Pi heartbeat/authority) — Phase 2 must consolidate, not duplicate.
- **1 genuinely missing, needed component**: the cross-capability task router (GAP-E8) — nothing routes across rule/cache/RAG/LLM/vision today.
- **0 areas show fabricated PASS status** — every BLOCKED/PARTIAL finding above is grounded in a specific code trace, matching rule 8's requirement.
