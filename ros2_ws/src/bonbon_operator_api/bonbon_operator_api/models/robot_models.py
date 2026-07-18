"""Robot state and status pydantic models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SafetyStateData(BaseModel):
    state: str = "unknown"  # normal | degraded | safety_stop | emergency_stop | unknown
    active_faults: list[str] = Field(default_factory=list)
    last_event_ts: float | None = None
    watchdog_ok: bool = True


class BatteryData(BaseModel):
    voltage_v: float = 0.0
    percentage: float = 0.0  # 0.0 – 100.0
    is_charging: bool = False
    estimated_runtime_min: float | None = None


class NavigationData(BaseModel):
    state: str = "idle"  # idle | navigating | paused | succeeded | failed
    current_x: float = 0.0
    current_y: float = 0.0
    current_yaw: float = 0.0
    goal_x: float | None = None
    goal_y: float | None = None
    progress_pct: float | None = None
    active_map: str | None = None


class PerceptionData(BaseModel):
    camera_active: bool = False
    lidar_active: bool = False
    persons_detected: int = 0
    obstacle_distance_m: float | None = None


class TTSData(BaseModel):
    is_speaking: bool = False
    current_text: str | None = None
    queue_depth: int = 0


class ConversationData(BaseModel):
    """Live view of the robot's own ASR/LLM/emotion pipeline -- what it just
    heard, said, and inferred about the person it's talking to. Distinct
    from the dashboard's operator-testbench fields (which record what the
    *operator* typed/spoke into their own browser for one-shot testing)."""

    # /speech/transcription (bonbon_msgs/SpeechTranscription)
    transcript_text: str = ""
    transcript_confidence: float = 0.0
    transcript_speaker_id: str = ""
    transcript_ts: float | None = None

    # /llm/response (bonbon_msgs/LLMResponse)
    llm_response_text: str = ""
    llm_status: str = "unknown"  # ok | low_conf | safety_block | hallucination | llm_error | fallback
    llm_confidence: float = 0.0
    llm_model_name: str = ""
    llm_ts: float | None = None

    # /bonbon/affective/human_state (bonbon_msgs/HumanEmotionState)
    emotion_dominant: str = "unknown"
    emotion_confidence: float = 0.0
    emotion_recommended_style: str = ""
    emotion_requires_operator_alert: bool = False
    emotion_ts: float | None = None


class ActuationData(BaseModel):
    linear_velocity_mps: float = 0.0
    angular_velocity_rps: float = 0.0
    motors_enabled: bool = False


class ModuleStatus(BaseModel):
    name: str
    state: str = "unknown"  # active | inactive | error | degraded | unknown
    health: str = "unknown"  # healthy | degraded | critical | unknown
    message: str = ""


class ComponentFaultData(BaseModel):
    """Mirrors bonbon_msgs/ComponentFault.msg -- sourced from
    bonbon_fault_manager's /bonbon/fault_manager/registry, NOT derived
    from ModuleStatus (that's node-liveness; this is per-hardware-part
    fault classification with concrete recovery guidance)."""

    component_id: str
    subsystem: str = "unknown"
    affected_pi: str = "unknown"
    fault_level: str = "OK"  # OK|WARNING|DEGRADED|FAULT|CRITICAL|BLOCKED
    error_code: str = ""
    message: str = ""
    recovery_action: str = ""
    dashboard_visible: bool = True
    occurrence_count: int = 0


class PerformanceData(BaseModel):
    """System performance snapshot. Sourced from bonbon_safety's
    ResourceUsage (always-on baseline) and bonbon_perception_efficiency's
    PerceptionEfficiencyMetrics (richer overlay, only present while that
    package is running) -- see ros2_bridge.py."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_free_percent: float = 100.0
    resource_data_available: bool = False  # false = psutil unavailable (sim/CI)
    load_level: str = "unknown"  # normal | reduced | minimal | critical | unknown
    recommended_load_shed: float = 1.0
    degraded_mode_active: bool = False
    avg_module_latency_ms: float | None = None
    max_module_latency_ms: float | None = None
    total_module_errors: int | None = None


class RobotStatus(BaseModel):
    """Aggregated snapshot of the full robot state."""

    is_online: bool = False
    uptime_sec: float = 0.0
    safety: SafetyStateData = Field(default_factory=SafetyStateData)
    battery: BatteryData = Field(default_factory=BatteryData)
    navigation: NavigationData = Field(default_factory=NavigationData)
    perception: PerceptionData = Field(default_factory=PerceptionData)
    tts: TTSData = Field(default_factory=TTSData)
    conversation: ConversationData = Field(default_factory=ConversationData)
    actuation: ActuationData = Field(default_factory=ActuationData)
    performance: PerformanceData = Field(default_factory=PerformanceData)
    modules: dict[str, ModuleStatus] = Field(default_factory=dict)
    component_faults: list[ComponentFaultData] = Field(default_factory=list)
    worst_fault_level: str = "OK"
    active_task: str | None = None
    last_updated: float = 0.0

    def overall_health(self) -> str:
        if not self.is_online:
            return "offline"
        if self.safety.state in ("emergency_stop", "safety_stop"):
            return "critical"
        if self.safety.state == "degraded" or self.battery.percentage < 15.0:
            return "degraded"
        return "healthy"


class DiagnosticEvent(BaseModel):
    event_id: str
    timestamp: float
    level: str  # info | warn | error | fatal
    source: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
