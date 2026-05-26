"""Robot state and status pydantic models."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SafetyStateData(BaseModel):
    state: str = "unknown"          # normal | degraded | safety_stop | emergency_stop | unknown
    active_faults: List[str] = Field(default_factory=list)
    last_event_ts: Optional[float] = None
    watchdog_ok: bool = True


class BatteryData(BaseModel):
    voltage_v: float = 0.0
    percentage: float = 0.0         # 0.0 – 100.0
    is_charging: bool = False
    estimated_runtime_min: Optional[float] = None


class NavigationData(BaseModel):
    state: str = "idle"             # idle | navigating | paused | succeeded | failed
    current_x: float = 0.0
    current_y: float = 0.0
    current_yaw: float = 0.0
    goal_x: Optional[float] = None
    goal_y: Optional[float] = None
    progress_pct: Optional[float] = None
    active_map: Optional[str] = None


class PerceptionData(BaseModel):
    camera_active: bool = False
    lidar_active: bool = False
    persons_detected: int = 0
    obstacle_distance_m: Optional[float] = None


class TTSData(BaseModel):
    is_speaking: bool = False
    current_text: Optional[str] = None
    queue_depth: int = 0


class ActuationData(BaseModel):
    linear_velocity_mps: float = 0.0
    angular_velocity_rps: float = 0.0
    motors_enabled: bool = False


class ModuleStatus(BaseModel):
    name: str
    state: str = "unknown"          # active | inactive | error | degraded | unknown
    health: str = "unknown"         # healthy | degraded | critical | unknown
    message: str = ""


class RobotStatus(BaseModel):
    """Aggregated snapshot of the full robot state."""
    is_online: bool = False
    uptime_sec: float = 0.0
    safety: SafetyStateData = Field(default_factory=SafetyStateData)
    battery: BatteryData = Field(default_factory=BatteryData)
    navigation: NavigationData = Field(default_factory=NavigationData)
    perception: PerceptionData = Field(default_factory=PerceptionData)
    tts: TTSData = Field(default_factory=TTSData)
    actuation: ActuationData = Field(default_factory=ActuationData)
    modules: Dict[str, ModuleStatus] = Field(default_factory=dict)
    active_task: Optional[str] = None
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
    level: str          # info | warn | error | fatal
    source: str
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
