# BonBon Failure-Mode Matrix

> Generated from `bonbon_safety/core/failure_catalog.py` — the single source of truth. Regenerate with `python -m bonbon_safety.tools.gen_matrix`. Integrity is enforced by `tests/test_failure_catalog.py`.

## Fallback levels

| Level | Meaning | Operator alert | Self-recoverable |
|---|---|---|---|
| L0 | normal operation | no | — |
| L1 | degraded mode | no | yes |
| L2 | safe pause | no | yes |
| L3 | safe stop | yes | yes |
| L4 | emergency stop | yes | no (manual reset) |
| L5 | human intervention required | yes | no |

## Sensor failures

| # | Failure | Module | Detection | Level | Recovery | User-facing | Operator alert | Test coverage |
|---|---|---|---|---|---|---|---|---|
| 1 | SENSOR_CAMERA_UNAVAILABLE | bonbon_hal/bonbon_vision | camera_node DriverFault / no frames within watchdog timeout | L1 degraded | reconnect driver (backoff); navigate on LIDAR only | vision-dependent features paused; robot keeps moving cautiously | no | catalog + handler integrity tests |
| 2 | SENSOR_CAMERA_CORRUPT_FRAME | bonbon_vision | FrameProcessor quality gate (size/encoding/all-black/NaN) | L1 degraded | drop frame; use last good; raise if sustained | momentary perception gap; no user-visible change | no | catalog + handler integrity tests |
| 3 | SENSOR_LOW_LIGHT | bonbon_vision | frame mean-luminance below threshold | L1 degraded | apply CLAHE; lower detection confidence; optionally announce | robot may ask to move to better light | no | catalog + handler integrity tests |
| 4 | SENSOR_FACE_NOT_DETECTED | bonbon_vision/bonbon_affective_ai | face pipeline returns zero faces | L0 normal | skip face emotion; fall back to voice/text modalities | interaction continues without facial cues | no | catalog + handler integrity tests |
| 5 | SENSOR_MULTIPLE_FACES | bonbon_vision | face pipeline returns >1 face | L0 normal | select nearest/most-central as primary; track others | robot focuses on the closest person | no | catalog + handler integrity tests |
| 6 | SENSOR_MIC_UNAVAILABLE | bonbon_hal/bonbon_speech | microphone_node DriverFault / no audio chunks | L1 degraded | reconnect driver; disable wake-word; enable touch/dashboard input | voice interaction unavailable; other inputs still work | no | catalog + handler integrity tests |
| 7 | SENSOR_SILENCE | bonbon_speech | VAD reports no speech for an extended window | L0 normal | remain in idle-listen; no action | robot waits quietly for input | no | catalog + handler integrity tests |
| 8 | SENSOR_NOISY_AUDIO | bonbon_speech | audio SNR below threshold / VAD instability | L1 degraded | raise VAD threshold; apply noise gate; request repeat | robot may ask the user to repeat | no | catalog + handler integrity tests |
| 9 | SENSOR_LIDAR_DISCONNECT | bonbon_hal/bonbon_safety | lidar_node DriverFault / scan watchdog stale | L2 safe-pause | reconnect; pause autonomous navigation while down | robot stops moving and holds position | yes | catalog + handler integrity tests |
| 10 | SENSOR_LIDAR_CORRUPT_SCAN | bonbon_hal/bonbon_safety | scan range NaN/Inf ratio or fixed-value ratio over threshold | L2 safe-pause | drop scan; pause nav if sustained; reconnect | robot pauses until clean scans resume | yes | catalog + handler integrity tests |
| 11 | SENSOR_IMU_DRIFT | bonbon_hal/bonbon_navigation | IMU bias/drift beyond tolerance vs. expected stationary | L1 degraded | recalibrate bias; down-weight IMU in odom fusion | navigation accuracy reduced; no user-visible change | no | catalog + handler integrity tests |
| 12 | SENSOR_ODOMETRY_JUMP | bonbon_navigation | pose delta exceeds physically-plausible step | L2 safe-pause | reject jump; trigger relocalization | robot pauses to re-establish its position | yes | catalog + handler integrity tests |
| 13 | SENSOR_TF_MISSING | bonbon_navigation | required tf2 transform unavailable within timeout | L2 safe-pause | wait + retry lookup; pause motion meanwhile | robot pauses until its frames are available | yes | catalog + handler integrity tests |
| 14 | SENSOR_BATTERY_UNAVAILABLE | bonbon_hal/bonbon_safety | battery_node DriverFault / battery state stale | L3 safe-stop | reconnect; assume worst-case charge → controlled stop | robot performs a controlled stop and seeks a dock | yes | catalog + handler integrity tests |

## AI failures

| # | Failure | Module | Detection | Level | Recovery | User-facing | Operator alert | Test coverage |
|---|---|---|---|---|---|---|---|---|
| 15 | AI_MODEL_FILE_MISSING | bonbon_vision/affective/gesture/llm | model path does not exist at configure time | L1 degraded | fall back to mock/deterministic backend | AI feature runs in reduced/mock mode | no | catalog + handler integrity tests |
| 16 | AI_MODEL_LOAD_FAILURE | bonbon_vision/affective/gesture/llm | backend import/load raises at configure | L1 degraded | catch + fall back to mock backend; log + diagnostic | AI feature runs in reduced/mock mode | no | catalog + handler integrity tests |
| 17 | AI_INFERENCE_TIMEOUT | bonbon_vision/affective/gesture/llm | inference exceeds per-call budget (ThreadPool future timeout) | L1 degraded | abandon result; reuse last good or mock; shed load | slightly stale perception; no user-visible change | no | catalog + handler integrity tests |
| 18 | AI_LOW_CONFIDENCE | bonbon_perception_ai/affective/gesture | top prediction confidence below threshold | L0 normal | treat as 'unknown'; ask for clarification if interactive | robot may ask the user to clarify | no | catalog + handler integrity tests |
| 19 | AI_LLM_HALLUCINATION | bonbon_llm | hallucination guard: ungrounded / unsupported claim | L1 degraded | discard; use static safe-response template | robot gives a safe, generic answer | no | catalog + handler integrity tests |
| 20 | AI_LLM_UNSAFE_PROPOSAL | bonbon_behavior_engine | CommandRiskClassifier flags critical/high risk at LLMCommandGate | L2 safe-pause | block proposal; never reaches actuation/nav; escalate | robot refuses the unsafe action and notifies staff | yes | catalog + handler integrity tests |
| 21 | AI_RAG_IRRELEVANT | bonbon_llm/bonbon_data_stores | retrieval similarity below relevance threshold | L0 normal | answer without RAG context / state insufficient info | robot answers from base knowledge only | no | catalog + handler integrity tests |
| 22 | AI_VECTOR_DB_UNAVAILABLE | bonbon_data_stores | FAISS/Chroma open or query raises | L1 degraded | disable RAG; in-memory fallback; reconnect later | answers lack long-term memory context | no | catalog + handler integrity tests |
| 23 | AI_EMOTION_MODEL_BAD | bonbon_affective_ai | DeepFace/SpeechBrain unavailable or returns invalid output | L1 degraded | fall back to mock backend / text-only sentiment | emotion sensing reduced; interaction continues | no | catalog + handler integrity tests |
| 24 | AI_GESTURE_FALSE_POSITIVE | bonbon_gesture | single-frame gesture not confirmed by temporal vote | L0 normal | temporal smoother majority vote + cooldown rejects it | spurious gestures are ignored | no | catalog + handler integrity tests |
| 25 | AI_SPEECH_MISRECOGNITION | bonbon_speech | low STT confidence / intent ambiguous | L0 normal | confirm intent with the user before acting | robot confirms before acting on a command | no | catalog + handler integrity tests |

## Actuation / navigation failures

| # | Failure | Module | Detection | Level | Recovery | User-facing | Operator alert | Test coverage |
|---|---|---|---|---|---|---|---|---|
| 26 | ACT_SERVO_UNAVAILABLE | bonbon_hal/bonbon_actuation | servo bus DriverFault / no servo state | L2 safe-pause | reconnect; suppress expressive motion while down | robot stops gesturing; speech still works | yes | catalog + handler integrity tests |
| 27 | ACT_SERVO_OVERHEAT | bonbon_hal/bonbon_actuation | ServoState temperature above safe threshold | L2 safe-pause | reduce duty cycle; rest servo until cooled | robot rests its arms/head briefly | yes | catalog + handler integrity tests |
| 28 | ACT_SERVO_STUCK | bonbon_actuation | commanded vs. reported position diverges beyond tolerance | L3 safe-stop | abort gesture; disable servo; require inspection | robot stops the motion and folds safely | yes | catalog + handler integrity tests |
| 29 | ACT_INVALID_JOINT_CMD | bonbon_actuation | ServoValidator: target outside mechanical limits | L1 degraded | clamp to limits or reject command | motion is limited to safe range | no | catalog + handler integrity tests |
| 30 | ACT_UNSAFE_GESTURE_NEAR_HUMAN | bonbon_actuation | ProximityGovernor: person inside arm-sweep stop band | L2 safe-pause | suppress arm-sweeping gestures; head-only motion | robot keeps its arms still near people | no | catalog + handler integrity tests |
| 31 | NAV_GOAL_UNREACHABLE | bonbon_navigation | planner repeatedly fails to find a path | L1 degraded | fail the goal; notify; await new goal | robot reports it cannot reach the destination | no | catalog + handler integrity tests |
| 32 | NAV_ROBOT_STUCK | bonbon_navigation | StuckDetector: commanded motion but no odom progress | L2 safe-pause | run recovery behaviours (back up / rotate / clear) | robot attempts to free itself, then waits | yes | catalog + handler integrity tests |
| 33 | NAV_BLOCKED_PATH | bonbon_spatial/bonbon_navigation | BlockageDetector: forward corridor occupied past persistence | L2 safe-pause | reroute if possible; else wait / ask to pass | robot pauses and says 'excuse me' / reroutes | no | catalog + handler integrity tests |
| 34 | NAV_RESTRICTED_ZONE | bonbon_spatial/bonbon_navigation | RestrictedZoneMonitor / planner enters restricted polygon | L2 safe-pause | reject/replan around the zone; escalate entry | robot avoids the restricted area | yes | catalog + handler integrity tests |
| 35 | NAV_TOO_CLOSE_TO_HUMAN | bonbon_spatial/bonbon_safety | PersonalSpaceEstimator: distance below stop band | L2 safe-pause | stop; maintain social distance; resume when clear | robot stops and keeps a polite distance | no | catalog + handler integrity tests |
| 36 | NAV_ESTOP_DURING_MOTION | bonbon_safety | hardware e-stop asserted while moving | L4 e-stop | cut motor power immediately; require manual reset | robot stops instantly; needs staff to reset | yes | catalog + handler integrity tests |

## System failures

| # | Failure | Module | Detection | Level | Recovery | User-facing | Operator alert | Test coverage |
|---|---|---|---|---|---|---|---|---|
| 37 | SYS_NODE_CRASH | bonbon_safety (watchdog) | watchdog: expected node heartbeat absent | L3 safe-stop | controlled stop; attempt lifecycle restart of the node | robot stops while the subsystem restarts | yes | catalog + handler integrity tests |
| 38 | SYS_SERVICE_UNAVAILABLE | any caller | service client wait_for_service timeout | L1 degraded | timeout + bounded retry; degrade the dependent feature | the dependent feature is temporarily unavailable | no | catalog + handler integrity tests |
| 39 | SYS_TOPIC_NOT_PUBLISHING | bonbon_safety (watchdog) | Watchdog staleness on a required topic | L2 safe-pause | pause features needing it; mark module STALE | robot pauses affected behaviour | yes | catalog + handler integrity tests |
| 40 | SYS_QUEUE_OVERFLOW | any node | bounded queue depth exceeded | L1 degraded | drop-oldest (or lowest priority); count drops | brief backlog; oldest low-priority work dropped | no | catalog + handler integrity tests |
| 41 | SYS_MEMORY_PRESSURE | bonbon_safety (system monitor) | process/system memory above high-water mark | L1 degraded | shed load: lower rates, clear caches | robot reduces processing rate | no | catalog + handler integrity tests |
| 42 | SYS_CPU_OVERLOAD | bonbon_safety (system monitor) | sustained CPU above threshold / cycle overruns | L1 degraded | reduce inference/publish rates; drop optional work | robot responds a little slower | no | catalog + handler integrity tests |
| 43 | SYS_DISK_FULL | bonbon_data_stores | free disk below threshold before write | L1 degraded | rotate/prune old logs; stop non-essential logging | non-critical logging paused | yes | catalog + handler integrity tests |
| 44 | SYS_DATABASE_LOCKED | bonbon_data_stores | SQLite 'database is locked' on write | L1 degraded | retry with backoff (busy_timeout); queue write | a record write is briefly delayed | no | catalog + handler integrity tests |
| 45 | SYS_CONFIG_MISSING | any node | required parameter / config file absent at configure | L3 safe-stop | use validated defaults if safe, else refuse to activate | subsystem will not start until configured | yes | catalog + handler integrity tests |
| 46 | SYS_CONFIG_INVALID | any node | config validation (typed config) fails | L3 safe-stop | reject config; remain unconfigured; report which field | subsystem will not start with bad config | yes | catalog + handler integrity tests |
| 47 | SYS_NETWORK_LOSS | bonbon_operator_api | WiFi/network link down | L1 degraded | operate autonomously offline; buffer telemetry | robot keeps working; dashboard updates when reconnected | no | catalog + handler integrity tests |
| 48 | SYS_DASHBOARD_DISCONNECT | bonbon_operator_api | operator websocket/client disconnect | L0 normal | keep running; buffer events for reconnect | no change to robot behaviour | no | catalog + handler integrity tests |
| 49 | SYS_BAD_OPERATOR_COMMAND | bonbon_operator_api/bonbon_behavior_engine | command fails validation / risk classifier | L1 degraded | reject with reason; never bypass the safety gate | operator sees a rejection with explanation | no | catalog + handler integrity tests |
| 50 | SYS_SHUTDOWN_DURING_WRITE | bonbon_data_stores | process signalled mid-write | L2 safe-pause | atomic/transactional writes (WAL); flush on shutdown hook | no data corruption; clean restart | no | catalog + handler integrity tests |
