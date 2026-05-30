"""Canonical catalogue of the 50 BonBon failure modes.

Each entry is a real :class:`FaultDefinition` — this module is both the
machine-readable registry consumed by :class:`FaultHandler` instances and the
single source of truth from which the failure-mode matrix
(``docs/FAILURE_MODES.md``) is generated. Tests assert the catalogue is complete
and internally consistent so the matrix can never silently drift from the code.

Fault id convention: ``<CATEGORY>_<SHORT_NAME>`` (stable, uppercase).
"""

from __future__ import annotations

from typing import Dict, List

from bonbon_safety.core.fault_handler import FaultDefinition, RecoveryPolicy
from bonbon_safety.core.fault_levels import FallbackLevel

_L = FallbackLevel


def _d(
    n: int, fault_id: str, module: str, detection: str, level: FallbackLevel,
    recovery: str, user_facing: str, operator_alert: bool,
    policy: RecoveryPolicy | None = None,
) -> tuple:
    """Build a (number, FaultDefinition) row."""
    return (
        n,
        FaultDefinition(
            fault_id=fault_id, module=module, detection=detection, level=level,
            recovery=recovery, user_facing=user_facing,
            operator_alert=operator_alert,
            policy=policy or RecoveryPolicy(),
        ),
    )


# Recovery-policy presets.
_FAST = RecoveryPolicy(max_attempts=3, backoff_sec=0.2, terminal_level=_L.DEGRADED)
_RECONNECT = RecoveryPolicy(max_attempts=5, backoff_sec=0.5, terminal_level=_L.SAFE_STOP)
_CRITICAL = RecoveryPolicy(max_attempts=2, backoff_sec=1.0, terminal_level=_L.HUMAN_REQUIRED)
_NORETRY = RecoveryPolicy(max_attempts=0, terminal_level=_L.HUMAN_REQUIRED)


# (number, FaultDefinition) — ordered exactly as the requirements enumerate them.
_ROWS: List[tuple] = [
    # ── Sensor failures (1–14) ───────────────────────────────────────────────
    _d(1, "SENSOR_CAMERA_UNAVAILABLE", "bonbon_hal/bonbon_vision",
       "camera_node DriverFault / no frames within watchdog timeout",
       _L.DEGRADED, "reconnect driver (backoff); navigate on LIDAR only",
       "vision-dependent features paused; robot keeps moving cautiously", False, _RECONNECT),
    _d(2, "SENSOR_CAMERA_CORRUPT_FRAME", "bonbon_vision",
       "FrameProcessor quality gate (size/encoding/all-black/NaN)",
       _L.DEGRADED, "drop frame; use last good; raise if sustained",
       "momentary perception gap; no user-visible change", False, _FAST),
    _d(3, "SENSOR_LOW_LIGHT", "bonbon_vision",
       "frame mean-luminance below threshold",
       _L.DEGRADED, "apply CLAHE; lower detection confidence; optionally announce",
       "robot may ask to move to better light", False, _FAST),
    _d(4, "SENSOR_FACE_NOT_DETECTED", "bonbon_vision/bonbon_affective_ai",
       "face pipeline returns zero faces",
       _L.NORMAL, "skip face emotion; fall back to voice/text modalities",
       "interaction continues without facial cues", False, _FAST),
    _d(5, "SENSOR_MULTIPLE_FACES", "bonbon_vision",
       "face pipeline returns >1 face",
       _L.NORMAL, "select nearest/most-central as primary; track others",
       "robot focuses on the closest person", False, _FAST),
    _d(6, "SENSOR_MIC_UNAVAILABLE", "bonbon_hal/bonbon_speech",
       "microphone_node DriverFault / no audio chunks",
       _L.DEGRADED, "reconnect driver; disable wake-word; enable touch/dashboard input",
       "voice interaction unavailable; other inputs still work", False, _RECONNECT),
    _d(7, "SENSOR_SILENCE", "bonbon_speech",
       "VAD reports no speech for an extended window",
       _L.NORMAL, "remain in idle-listen; no action",
       "robot waits quietly for input", False, _FAST),
    _d(8, "SENSOR_NOISY_AUDIO", "bonbon_speech",
       "audio SNR below threshold / VAD instability",
       _L.DEGRADED, "raise VAD threshold; apply noise gate; request repeat",
       "robot may ask the user to repeat", False, _FAST),
    _d(9, "SENSOR_LIDAR_DISCONNECT", "bonbon_hal/bonbon_safety",
       "lidar_node DriverFault / scan watchdog stale",
       _L.SAFE_PAUSE, "reconnect; pause autonomous navigation while down",
       "robot stops moving and holds position", True, _RECONNECT),
    _d(10, "SENSOR_LIDAR_CORRUPT_SCAN", "bonbon_hal/bonbon_safety",
       "scan range NaN/Inf ratio or fixed-value ratio over threshold",
       _L.SAFE_PAUSE, "drop scan; pause nav if sustained; reconnect",
       "robot pauses until clean scans resume", True, _RECONNECT),
    _d(11, "SENSOR_IMU_DRIFT", "bonbon_hal/bonbon_navigation",
       "IMU bias/drift beyond tolerance vs. expected stationary",
       _L.DEGRADED, "recalibrate bias; down-weight IMU in odom fusion",
       "navigation accuracy reduced; no user-visible change", False, _FAST),
    _d(12, "SENSOR_ODOMETRY_JUMP", "bonbon_navigation",
       "pose delta exceeds physically-plausible step",
       _L.SAFE_PAUSE, "reject jump; trigger relocalization",
       "robot pauses to re-establish its position", True, _RECONNECT),
    _d(13, "SENSOR_TF_MISSING", "bonbon_navigation",
       "required tf2 transform unavailable within timeout",
       _L.SAFE_PAUSE, "wait + retry lookup; pause motion meanwhile",
       "robot pauses until its frames are available", True, _RECONNECT),
    _d(14, "SENSOR_BATTERY_UNAVAILABLE", "bonbon_hal/bonbon_safety",
       "battery_node DriverFault / battery state stale",
       _L.SAFE_STOP, "reconnect; assume worst-case charge → controlled stop",
       "robot performs a controlled stop and seeks a dock", True, _CRITICAL),

    # ── AI failures (15–25) ──────────────────────────────────────────────────
    _d(15, "AI_MODEL_FILE_MISSING", "bonbon_vision/affective/gesture/llm",
       "model path does not exist at configure time",
       _L.DEGRADED, "fall back to mock/deterministic backend",
       "AI feature runs in reduced/mock mode", False, _NORETRY),
    _d(16, "AI_MODEL_LOAD_FAILURE", "bonbon_vision/affective/gesture/llm",
       "backend import/load raises at configure",
       _L.DEGRADED, "catch + fall back to mock backend; log + diagnostic",
       "AI feature runs in reduced/mock mode", False, _NORETRY),
    _d(17, "AI_INFERENCE_TIMEOUT", "bonbon_vision/affective/gesture/llm",
       "inference exceeds per-call budget (ThreadPool future timeout)",
       _L.DEGRADED, "abandon result; reuse last good or mock; shed load",
       "slightly stale perception; no user-visible change", False, _FAST),
    _d(18, "AI_LOW_CONFIDENCE", "bonbon_perception_ai/affective/gesture",
       "top prediction confidence below threshold",
       _L.NORMAL, "treat as 'unknown'; ask for clarification if interactive",
       "robot may ask the user to clarify", False, _FAST),
    _d(19, "AI_LLM_HALLUCINATION", "bonbon_llm",
       "hallucination guard: ungrounded / unsupported claim",
       _L.DEGRADED, "discard; use static safe-response template",
       "robot gives a safe, generic answer", False, _FAST),
    _d(20, "AI_LLM_UNSAFE_PROPOSAL", "bonbon_behavior_engine",
       "CommandRiskClassifier flags critical/high risk at LLMCommandGate",
       _L.SAFE_PAUSE, "block proposal; never reaches actuation/nav; escalate",
       "robot refuses the unsafe action and notifies staff", True, _NORETRY),
    _d(21, "AI_RAG_IRRELEVANT", "bonbon_llm/bonbon_data_stores",
       "retrieval similarity below relevance threshold",
       _L.NORMAL, "answer without RAG context / state insufficient info",
       "robot answers from base knowledge only", False, _FAST),
    _d(22, "AI_VECTOR_DB_UNAVAILABLE", "bonbon_data_stores",
       "FAISS/Chroma open or query raises",
       _L.DEGRADED, "disable RAG; in-memory fallback; reconnect later",
       "answers lack long-term memory context", False, _RECONNECT),
    _d(23, "AI_EMOTION_MODEL_BAD", "bonbon_affective_ai",
       "DeepFace/SpeechBrain unavailable or returns invalid output",
       _L.DEGRADED, "fall back to mock backend / text-only sentiment",
       "emotion sensing reduced; interaction continues", False, _NORETRY),
    _d(24, "AI_GESTURE_FALSE_POSITIVE", "bonbon_gesture",
       "single-frame gesture not confirmed by temporal vote",
       _L.NORMAL, "temporal smoother majority vote + cooldown rejects it",
       "spurious gestures are ignored", False, _FAST),
    _d(25, "AI_SPEECH_MISRECOGNITION", "bonbon_speech",
       "low STT confidence / intent ambiguous",
       _L.NORMAL, "confirm intent with the user before acting",
       "robot confirms before acting on a command", False, _FAST),

    # ── Actuation / navigation failures (26–36) ───────────────────────────────
    _d(26, "ACT_SERVO_UNAVAILABLE", "bonbon_hal/bonbon_actuation",
       "servo bus DriverFault / no servo state",
       _L.SAFE_PAUSE, "reconnect; suppress expressive motion while down",
       "robot stops gesturing; speech still works", True, _RECONNECT),
    _d(27, "ACT_SERVO_OVERHEAT", "bonbon_hal/bonbon_actuation",
       "ServoState temperature above safe threshold",
       _L.SAFE_PAUSE, "reduce duty cycle; rest servo until cooled",
       "robot rests its arms/head briefly", True, _FAST),
    _d(28, "ACT_SERVO_STUCK", "bonbon_actuation",
       "commanded vs. reported position diverges beyond tolerance",
       _L.SAFE_STOP, "abort gesture; disable servo; require inspection",
       "robot stops the motion and folds safely", True, _CRITICAL),
    _d(29, "ACT_INVALID_JOINT_CMD", "bonbon_actuation",
       "ServoValidator: target outside mechanical limits",
       _L.DEGRADED, "clamp to limits or reject command",
       "motion is limited to safe range", False, _FAST),
    _d(30, "ACT_UNSAFE_GESTURE_NEAR_HUMAN", "bonbon_actuation",
       "ProximityGovernor: person inside arm-sweep stop band",
       _L.SAFE_PAUSE, "suppress arm-sweeping gestures; head-only motion",
       "robot keeps its arms still near people", False, _FAST),
    _d(31, "NAV_GOAL_UNREACHABLE", "bonbon_navigation",
       "planner repeatedly fails to find a path",
       _L.DEGRADED, "fail the goal; notify; await new goal",
       "robot reports it cannot reach the destination", False, _FAST),
    _d(32, "NAV_ROBOT_STUCK", "bonbon_navigation",
       "StuckDetector: commanded motion but no odom progress",
       _L.SAFE_PAUSE, "run recovery behaviours (back up / rotate / clear)",
       "robot attempts to free itself, then waits", True, _RECONNECT),
    _d(33, "NAV_BLOCKED_PATH", "bonbon_spatial/bonbon_navigation",
       "BlockageDetector: forward corridor occupied past persistence",
       _L.SAFE_PAUSE, "reroute if possible; else wait / ask to pass",
       "robot pauses and says 'excuse me' / reroutes", False, _FAST),
    _d(34, "NAV_RESTRICTED_ZONE", "bonbon_spatial/bonbon_navigation",
       "RestrictedZoneMonitor / planner enters restricted polygon",
       _L.SAFE_PAUSE, "reject/replan around the zone; escalate entry",
       "robot avoids the restricted area", True, _FAST),
    _d(35, "NAV_TOO_CLOSE_TO_HUMAN", "bonbon_spatial/bonbon_safety",
       "PersonalSpaceEstimator: distance below stop band",
       _L.SAFE_PAUSE, "stop; maintain social distance; resume when clear",
       "robot stops and keeps a polite distance", False, _FAST),
    _d(36, "NAV_ESTOP_DURING_MOTION", "bonbon_safety",
       "hardware e-stop asserted while moving",
       _L.EMERGENCY_STOP, "cut motor power immediately; require manual reset",
       "robot stops instantly; needs staff to reset", True, _NORETRY),

    # ── System failures (37–50) ───────────────────────────────────────────────
    _d(37, "SYS_NODE_CRASH", "bonbon_safety (watchdog)",
       "watchdog: expected node heartbeat absent",
       _L.SAFE_STOP, "controlled stop; attempt lifecycle restart of the node",
       "robot stops while the subsystem restarts", True, _RECONNECT),
    _d(38, "SYS_SERVICE_UNAVAILABLE", "any caller",
       "service client wait_for_service timeout",
       _L.DEGRADED, "timeout + bounded retry; degrade the dependent feature",
       "the dependent feature is temporarily unavailable", False, _FAST),
    _d(39, "SYS_TOPIC_NOT_PUBLISHING", "bonbon_safety (watchdog)",
       "Watchdog staleness on a required topic",
       _L.SAFE_PAUSE, "pause features needing it; mark module STALE",
       "robot pauses affected behaviour", True, _RECONNECT),
    _d(40, "SYS_QUEUE_OVERFLOW", "any node",
       "bounded queue depth exceeded",
       _L.DEGRADED, "drop-oldest (or lowest priority); count drops",
       "brief backlog; oldest low-priority work dropped", False, _FAST),
    _d(41, "SYS_MEMORY_PRESSURE", "bonbon_safety (system monitor)",
       "process/system memory above high-water mark",
       _L.DEGRADED, "shed load: lower rates, clear caches",
       "robot reduces processing rate", False, _FAST),
    _d(42, "SYS_CPU_OVERLOAD", "bonbon_safety (system monitor)",
       "sustained CPU above threshold / cycle overruns",
       _L.DEGRADED, "reduce inference/publish rates; drop optional work",
       "robot responds a little slower", False, _FAST),
    _d(43, "SYS_DISK_FULL", "bonbon_data_stores",
       "free disk below threshold before write",
       _L.DEGRADED, "rotate/prune old logs; stop non-essential logging",
       "non-critical logging paused", True, _FAST),
    _d(44, "SYS_DATABASE_LOCKED", "bonbon_data_stores",
       "SQLite 'database is locked' on write",
       _L.DEGRADED, "retry with backoff (busy_timeout); queue write",
       "a record write is briefly delayed", False, _FAST),
    _d(45, "SYS_CONFIG_MISSING", "any node",
       "required parameter / config file absent at configure",
       _L.SAFE_STOP, "use validated defaults if safe, else refuse to activate",
       "subsystem will not start until configured", True, _NORETRY),
    _d(46, "SYS_CONFIG_INVALID", "any node",
       "config validation (typed config) fails",
       _L.SAFE_STOP, "reject config; remain unconfigured; report which field",
       "subsystem will not start with bad config", True, _NORETRY),
    _d(47, "SYS_NETWORK_LOSS", "bonbon_operator_api",
       "WiFi/network link down",
       _L.DEGRADED, "operate autonomously offline; buffer telemetry",
       "robot keeps working; dashboard updates when reconnected", False, _RECONNECT),
    _d(48, "SYS_DASHBOARD_DISCONNECT", "bonbon_operator_api",
       "operator websocket/client disconnect",
       _L.NORMAL, "keep running; buffer events for reconnect",
       "no change to robot behaviour", False, _FAST),
    _d(49, "SYS_BAD_OPERATOR_COMMAND", "bonbon_operator_api/bonbon_behavior_engine",
       "command fails validation / risk classifier",
       _L.DEGRADED, "reject with reason; never bypass the safety gate",
       "operator sees a rejection with explanation", False, _FAST),
    _d(50, "SYS_SHUTDOWN_DURING_WRITE", "bonbon_data_stores",
       "process signalled mid-write",
       _L.SAFE_PAUSE, "atomic/transactional writes (WAL); flush on shutdown hook",
       "no data corruption; clean restart", False, _FAST),
]


def build_catalog() -> Dict[str, FaultDefinition]:
    """Return the full {fault_id: FaultDefinition} registry."""
    return {defn.fault_id: defn for _, defn in _ROWS}


def numbered_catalog() -> List[tuple]:
    """Return the ordered [(number, FaultDefinition), …] list."""
    return list(_ROWS)


# Categories for grouping in the matrix.
CATEGORY_RANGES = {
    "Sensor failures": (1, 14),
    "AI failures": (15, 25),
    "Actuation / navigation failures": (26, 36),
    "System failures": (37, 50),
}
