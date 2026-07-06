# Pi-2 Deployment File Audit

Generated: 2026-07-06, before any code transfer to the physical Pi-2 board (`wise150@192.168.1.16`).
Ground truth sourced from `bonbon_human_ai_bringup/README.md` + its launch file,
`config/distributed/pi_human_ai.yaml`, and `deployment/compose/docker-compose.pi2.yml`
(the authoritative existing definition of Pi-2's package set) — not from a generic assumed
package list. Several package names commonly assumed for a project like this
(`bonbon_pi2_bringup`, `bonbon_vad`, `bonbon_asr`, `bonbon_face_recognition`, `bonbon_rag`,
`bonbon_common_msgs`, `bonbon_interfaces`, `bonbon_diagnostics`, `bonbon_distributed_communication`)
**do not exist as separate packages** — their functionality is already implemented inside other,
real packages listed below. Creating separate packages for them would be pure duplication.

One real gap was found and fixed as part of this audit (see `bonbon_behavior_engine` row) —
already committed to git, not merely noted.

## Package classification table

| Package | Required for Pi-2 | Reason | Python deps | System deps | Hardware dep | Launch file | Config file | Tests | Deployment status |
|---|---|---|---|---|---|---|---|---|---|
| `bonbon_human_ai_bringup` | Yes | Composes all Pi-2 subsystem launches in correct boot order; explicitly disables Pi-3 HAL (lidar/motor/servo/stepper/estop/battery) so this can never launch Pi-3 hardware nodes | none (composition only) | none | none | `human_ai_bringup.launch.py` | `config/pi2_hal_overrides.yaml` | none (pure orchestration, nothing to unit test) | Ready — `bonbon_behavior_engine` was missing from its launch composition and package.xml; **fixed this session** |
| `bonbon_hal` (camera/mic/speaker only) | Yes | OAK-D Lite / ReSpeaker / ALSA+PAM8610 drivers. Same package Pi-3 uses for motor/servo/lidar — launched here with `launch_camera/mic/speaker:=true`, everything else `:=false` | `smbus2`, `pyserial` (unused on Pi-2), `sounddevice`, `numpy` | ALSA (`libasound2`), USB | Yes — OAK-D Lite, ReSpeaker XVF3800, ALSA speaker/PAM8610 | `hal.launch.py` (shared with Pi-3) | `hal_params.yaml` + `pi2_hal_overrides.yaml` | 232 tests (whole package, includes Pi-3-only drivers) | Ready |
| `bonbon_vision` | Yes | OAK-D object detection (YOLO) + face detection/ID (InsightFace/DeepFace) + privacy anonymization. **Face recognition lives here — no separate package** | `numpy`, OpenCV, `ultralytics`, `insightface`, `deepface`, `depthai` | OpenCV native libs | Yes — OAK-D Lite | `vision.launch.py` | none | 13 files | Ready |
| `bonbon_speech` | Yes | Silero VAD + Whisper STT + pyannote diarization + audio capture. **VAD and ASR live here — no separate packages** | `numpy`, `speechrecognition`, `librosa`, `pyannote.audio`, `silero-vad`, `openai-whisper` | `portaudio19-dev`/ALSA | Yes — ReSpeaker XVF3800 | `speech.launch.py` | none | 12 files (153 tests, all passing) | Ready |
| `bonbon_llm` | Yes | Ollama-backed local Qwen2.5:0.5b gateway, LangChain chains, safety-filtered command interpretation. **RAG (ChromaDB/FAISS) lives here — no separate `bonbon_rag`** | `ollama` (Python SDK), `langchain`, `chromadb`/`faiss-cpu`, `sentence-transformers` | none beyond Python | No (talks to local Ollama HTTP API) | `llm.launch.py` (3s delayed start) | code-embedded `LLMConfig`/`RAGConfig` | 15 files | Ready — depends on Ollama being installed + `qwen2.5:0.5b` pulled on host (Phase 8) |
| `bonbon_tts` | Yes | Text-to-speech for behavior responses/interaction | TTS backend (gTTS/pyttsx3) | ALSA output | Yes — speaker (shared with `bonbon_hal`'s speaker driver for playback) | `tts.launch.py` | `tts_params.yaml` | 9 files | Ready |
| `bonbon_multi_person_tracker` | Yes | Persists identity across frames, PersonState lifecycle, multi-person state array | `numpy` | none | Indirect (consumes `bonbon_vision` output) | `multi_person_tracker.launch.py` | none | 6 files | Ready |
| `bonbon_object_intelligence` | Yes | General object detection/classification beyond person/face | `numpy` | none | Indirect (OAK-D via `bonbon_vision`) | `object_intelligence.launch.py` | none | included in perception suite | Ready |
| `bonbon_gesture` | Yes | **Input-side** human gesture recognition (MediaPipe Holistic landmarks + safety classification). Distinct from Pi-3's `bonbon_actuation` gesture *execution* library — do not confuse the two | `numpy`, MediaPipe | none | Indirect (OAK-D via `bonbon_vision`) | `gesture.launch.py` | `gesture.yaml` | 10 files | Ready |
| `bonbon_affective_ai` | Yes | Multi-human emotion: face (InsightFace) + voice prosody + text sentiment (`transformers`) fusion | `numpy`, `transformers` | none | Indirect (camera + mic) | `affective_ai.launch.py` | `affective_ai.yaml` | 9 files | Ready |
| `bonbon_human_state_fusion` | Yes | Fuses tracker + affective + gesture + speaker-intel into one per-person state | `numpy` | none | none (pure fusion) | `human_state_fusion.launch.py` | none | 8 files | Ready |
| `bonbon_speaker_intelligence` | Yes | Speaker ID + transcript attribution, feeds human_state_fusion | `numpy` | none | Indirect (mic) | `speaker_intelligence.launch.py` | none | included in perception suite | Ready |
| `bonbon_behavior_engine` | Yes | Fuses LLM + emotion + gesture + speech into `BehaviorProposal` messages sent toward Pi-3. **Proposes only — never commands motion directly; Pi-3's safety_gate_node/motion_approval_gateway is the sole approval authority** | none beyond `rclpy` | none | none | `behavior_engine.launch.py` | `behavior_engine.yaml` | 164 tests, all passing | **Gap found: was only wired into the monolithic `bonbon_bringup`, absent from `bonbon_human_ai_bringup`'s launch composition, its `package.xml`, and `docker-compose.pi2.yml` — meaning Pi-2's distributed deployment never actually sent behavior proposals to Pi-3. Fixed this session** (all three files) |
| `bonbon_ai_runtime` | Yes (library, not a node) | Pluggable inference backend abstraction (CPU/ONNX/TensorRT/Hailo/mock) used by `bonbon_vision` | `onnxruntime`; `hailort`/`tensorrt` optional | none required | Optional — Hailo-10H present on Pi-2 BOM, **not yet integrated** (Phase 10, separate scope) | none (library) | none | 3 files | Ready in CPU/ONNX mode; Hailo backend deferred |
| `bonbon_data_feedback` | **No — corrected after verification** | Originally listed as required; grepped every Pi-2 package's source for an actual import and found none. `bonbon_llm`'s RAG is self-contained (own ChromaDB/FAISS code), doesn't delegate to this package. Confirmed absent from `Dockerfile.ai`'s `COPY` list too (that list is independently derived by walking `package.xml` `exec_depend`s to a fixed point) | — | — | — | — | — | 10 files (exist, just not consumed by Pi-2) | Correctly excluded from the Pi-2 bundle |
| `bonbon_data_stores` | **No — corrected after verification** | Same finding as above — no Pi-2 package imports it; not in `Dockerfile.ai` | — | — | — | — | — | 9 files (exist, just not consumed by Pi-2) | Correctly excluded from the Pi-2 bundle |
| `bonbon_perception_efficiency` | Yes | Pi-2 resource governor: confidence policy, frame sampling, stale-frame dropping, CPU/temp-based shedding across all perception nodes | `numpy` | none | none | `perception_efficiency.launch.py` | none | 13 files | Ready |
| `bonbon_distributed_safety` | Yes | Publishes `/bonbon/pi2/heartbeat`, monitors Pi-1/Pi-3 liveness | `rclpy` only | none | none | run directly (`self_id:=pi2` param), no dedicated launch file needed | none | 2 files | Ready |
| `bonbon_authority_manager` | Yes | Applies `failure_policy.yaml` locally; degrades Pi-2 behavior if peers unreachable | `rclpy` only | none | none | run directly (`self_id:=pi2` param) | none | 2 files | Ready |
| `bonbon_msgs` / `bonbon_srvs` | Yes | Shared interface definitions (`PersonState`, `HumanAffectiveState`, `BehaviorProposal`, `ServoState`, `HalFault`, `ModuleHealth`, etc.) — true single source of truth | none (msg/srv only) | ROS2 message generation | none | n/a | n/a | n/a | Ready |
| `bonbon_fault_manager` | **No — runs on Pi-1, not Pi-2** | Aggregates `/bonbon/hal/fault` + `/bonbon/safety/state` network-wide via DDS; co-located with the Pi-1 dashboard it feeds. Pi-2 only needs to *publish* `HalFault`/`ModuleHealth` (already automatic via `HalNodeBase`/`DriverBase`, no extra package needed on Pi-2) | — | — | — | — | — | — | Correctly excluded from Pi-2 bundle |
| `bonbon_ui_api_bringup`, `bonbon_operator_api`, dashboard frontend | **No — Pi-1 only** | Touchscreen/dashboard/API is Pi-1's role | — | — | — | — | — | — | Correctly excluded |
| `bonbon_navigation_bringup`, `bonbon_base_controller`, `bonbon_navigation`, `bonbon_actuation`, `bonbon_motion_approval_gateway`, `bonbon_safety` | **No — Pi-3 only** | Motor/servo/stepper/lidar/navigation/safety-gate is Pi-3's role. `bonbon_hal`'s lidar/motor/servo/stepper/estop/battery drivers are explicitly disabled in Pi-2's launch (`launch_lidar:=false` etc.) so no duplicate hardware pipeline can start here | — | — | — | — | — | — | Correctly excluded |
| `bonbon_diagnostics` | **Does not exist as a separate package** | Diagnostics function is provided by `bonbon_fault_manager` (Pi-1) + `ModuleHealth` heartbeats every node already publishes | — | — | — | — | — | — | N/A — not a gap, just a naming mismatch against the generic template |
| `bonbon_common_msgs` / `bonbon_interfaces` | **Does not exist** | Same role already served by `bonbon_msgs`/`bonbon_srvs` | — | — | — | — | — | — | N/A |
| `bonbon_distributed_communication` | **Does not exist as a single package** | Same role already served by `bonbon_distributed_safety` + `bonbon_authority_manager` | — | — | — | — | — | — | N/A |
| `bonbon_pi2_bringup` | **Does not exist — do not create** | `bonbon_human_ai_bringup` already is the Pi-2 bringup package; creating a second one would be exactly the redundancy this deployment must avoid | — | — | — | — | — | — | N/A |
| `bonbon_face_recognition`, `bonbon_vad`, `bonbon_asr`, `bonbon_rag`, `bonbon_local_llm_gateway` | **Do not exist as separate packages** | Face recognition lives in `bonbon_vision`; VAD+ASR live in `bonbon_speech`; RAG+LLM gateway live in `bonbon_llm` | — | — | — | — | — | — | N/A |

## Flagged but NOT acted on: `bonbon_perception_ai`

`Dockerfile.ai` copies and colcon-builds `bonbon_perception_ai` (scene/intent/risk semantic fusion,
publishing `/perception/scene`, `/perception/intent`, `/perception/risks`, `/perception/behavior`),
but it is **not** included in `bonbon_human_ai_bringup`'s launch, its `package.xml`, or
`docker-compose.pi2.yml` — so it's built into the image but never actually launched. Checked whether
this is the same class of bug as the `bonbon_behavior_engine` gap above: it is not, or at least not
unambiguously. `bonbon_behavior_engine` subscribes to `/bonbon/affective/human_state` and
`/bonbon/human/state` (from `bonbon_affective_ai`/`bonbon_human_state_fusion`) — it does **not**
subscribe to any of `bonbon_perception_ai`'s topics. That means `bonbon_perception_ai` is either
(a) an earlier iteration of scene/intent fusion superseded by the
`bonbon_human_state_fusion` → `bonbon_behavior_engine` pipeline that now exists, correctly left
unlaunched to avoid a second, overlapping semantic-fusion pipeline, or (b) a genuinely
complementary risk/intent layer that was simply never wired up. Deciding which without more
context risks creating exactly the duplicate-pipeline problem this deployment must avoid — so
this is left as a flagged, deferred item rather than acted on unilaterally. It does not block Pi-2
deployment (the wired-in path is complete and unambiguous); it's a candidate for a future,
deliberate architecture decision, not this deployment pass.

## Verdict

17/17 Pi-2 responsibility areas map to real, tested, non-duplicate packages. One real integration
gap (`bonbon_behavior_engine` never wired into the distributed Pi-2 path) was found and fixed
directly rather than merely reported. No new packages need to be created for this deployment.
Proceeding to Phase 3 (bundle) using this package list, transferred via the `bonbon/ai` Docker image
path (see `docs/PI2_RASPBERRY_PI_PREFLIGHT_REPORT.md` for why Docker rather than bare-metal ROS2 on
this specific host OS).
