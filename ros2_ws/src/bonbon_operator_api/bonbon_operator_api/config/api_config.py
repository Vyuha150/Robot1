"""OperatorAPIConfig — central pydantic v2 configuration.

JWT_SECRET is NEVER hardcoded.  It must be supplied via the
``BONBON_JWT_SECRET`` environment variable or a ROS2 parameter.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class CORSConfig(BaseModel):
    allowed_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8080",
        ]
    )
    allow_credentials: bool = True
    allowed_methods: List[str] = Field(default_factory=lambda: ["*"])
    allowed_headers: List[str] = Field(default_factory=lambda: ["*"])


class JWTConfig(BaseModel):
    secret: str = Field(default="", description="MUST be set via BONBON_JWT_SECRET env var.")
    algorithm: str = "HS256"
    token_expire_minutes: int = Field(default=60, ge=5, le=1440)

    @model_validator(mode="after")
    def _require_secret(self) -> "JWTConfig":
        if not self.secret:
            env_secret = os.environ.get("BONBON_JWT_SECRET", "")
            if not env_secret:
                # In test mode, generate a random secret; raise in production
                if os.environ.get("BONBON_TEST_MODE", "0") == "1":
                    object.__setattr__(self, "secret", secrets.token_urlsafe(32))
                else:
                    raise ValueError(
                        "BONBON_JWT_SECRET environment variable must be set. "
                        "Example: export BONBON_JWT_SECRET=$(openssl rand -hex 32)"
                    )
            else:
                object.__setattr__(self, "secret", env_secret)
        return self


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1024, le=65535)
    workers: int = Field(default=1, ge=1, le=8)
    log_level: str = "INFO"
    debug: bool = False
    reload: bool = False


class ROS2Config(BaseModel):
    enabled: bool = True                # set False to run without ROS2 (tests, dev)
    namespace: str = "/bonbon"
    offline_timeout_sec: float = Field(default=15.0, ge=2.0)
    service_timeout_sec: float = Field(default=5.0, ge=0.5, le=30.0)
    status_update_interval_sec: float = Field(default=0.5, ge=0.25, le=2.0)

    # Topics — subscribers
    topic_safety_state: str = "/bonbon/safety/state"
    topic_battery: str = "/bonbon/battery/status"
    topic_nav_state: str = "/bonbon/navigation/state"
    topic_perception: str = "/bonbon/perception/status"
    topic_tts_state: str = "/bonbon/tts/state"
    topic_actuation: str = "/bonbon/actuation/state"
    topic_module_status: str = "/bonbon/modules/status"
    topic_heartbeat: str = "/bonbon/heartbeat"

    # Services
    srv_emergency_stop: str = "/bonbon/safety/emergency_stop"
    srv_speak: str = "/bonbon/tts/speak"
    srv_navigate: str = "/bonbon/navigation/navigate"
    srv_pause: str = "/bonbon/navigation/pause"
    srv_resume: str = "/bonbon/navigation/resume"
    srv_dock: str = "/bonbon/navigation/dock"
    srv_cancel_task: str = "/bonbon/task/cancel"
    srv_restart_module: str = "/bonbon/modules/restart"
    srv_get_config: str = "/bonbon/config/get"
    srv_set_config: str = "/bonbon/config/set"
    srv_memory_query: str = "/bonbon/memory/query"
    srv_rag_query: str = "/bonbon/rag/query"


class AuditConfig(BaseModel):
    db_path: Path = Field(default=Path("/tmp/bonbon/operator_api/audit.db"))
    max_events: int = Field(default=100_000, ge=1000)
    retention_days: int = Field(default=90, ge=7)

    @model_validator(mode="after")
    def _ensure_dir(self) -> "AuditConfig":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return self


class MetricsConfig(BaseModel):
    enabled: bool = True
    port: int = Field(default=9090, ge=1024, le=65535)
    path: str = "/metrics"


class RateLimitConfig(BaseModel):
    command_per_minute: int = Field(default=30, ge=1)
    login_per_minute: int = Field(default=10, ge=1)
    ws_connections_per_user: int = Field(default=5, ge=1)


# ---------------------------------------------------------------------------
# Critical vs limited config parameters
# ---------------------------------------------------------------------------

CRITICAL_CONFIG_KEYS = frozenset({
    "safety.emergency_distance_m",
    "safety.watchdog_timeout_sec",
    "navigation.max_speed_mps",
    "navigation.obstacle_distance_m",
})

LIMITED_CONFIG_KEYS = frozenset({
    "tts.default_volume",
    "tts.default_language",
    "navigation.preferred_speed_mps",
    "perception.detection_confidence_threshold",
    "robot.interaction_timeout_sec",
})


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class OperatorAPIConfig(BaseModel):
    """Root configuration for the bonbon_operator_api package."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    jwt: JWTConfig = Field(default_factory=JWTConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    ros2: ROS2Config = Field(default_factory=ROS2Config)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    users_db_path: Path = Field(default=Path("/tmp/bonbon/operator_api/users.db"))
    config_store_path: Path = Field(
        default=Path("/tmp/bonbon/operator_api/robot_config.json")
    )
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "OperatorAPIConfig":
        """Build config reading secrets from environment variables."""
        return cls()

    @model_validator(mode="after")
    def _ensure_dirs(self) -> "OperatorAPIConfig":
        self.users_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_store_path.parent.mkdir(parents=True, exist_ok=True)
        return self
