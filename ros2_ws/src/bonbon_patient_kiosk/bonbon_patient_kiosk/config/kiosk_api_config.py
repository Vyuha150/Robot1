"""KioskAPIConfig — central pydantic v2 configuration.

Mirrors bonbon_operator_api's OperatorAPIConfig structure. JWT_SECRET is
NEVER hardcoded — it must come from BONBON_KIOSK_JWT_SECRET or a ROS2
parameter. Staff-only endpoints (Facility Map Editor, admin) reuse this
same secret; patients never authenticate at all — the public kiosk flow
is session-scoped, not account-scoped (see data/store.py).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


def _default_cors_origins() -> list[str]:
    base = [
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://localhost:4174",
        "http://127.0.0.1:4174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ]
    extra = os.environ.get("BONBON_KIOSK_CORS_ORIGINS", "")
    for origin in (o.strip() for o in extra.split(",")):
        if origin and origin not in base:
            base.append(origin)
    return base


class CORSConfig(BaseModel):
    allowed_origins: list[str] = Field(default_factory=_default_cors_origins)
    allow_credentials: bool = True
    allowed_methods: list[str] = Field(default_factory=lambda: ["*"])
    allowed_headers: list[str] = Field(default_factory=lambda: ["*"])


class JWTConfig(BaseModel):
    """Signs staff-only tokens (Facility Map Editor / admin). Patients never
    receive a JWT — their kiosk session uses an opaque, short-lived session
    id instead (see SessionConfig)."""

    secret: str = Field(default="")
    algorithm: str = "HS256"
    token_expire_minutes: int = Field(default=60, ge=5, le=1440)

    @model_validator(mode="after")
    def _require_secret(self) -> "JWTConfig":
        if not self.secret:
            env_secret = os.environ.get("BONBON_KIOSK_JWT_SECRET", "")
            if not env_secret:
                if os.environ.get("BONBON_TEST_MODE", "0") == "1":
                    object.__setattr__(self, "secret", secrets.token_urlsafe(32))
                else:
                    raise ValueError(
                        "BONBON_KIOSK_JWT_SECRET environment variable must be set. "
                        "Generate one with: openssl rand -hex 32, then export it."
                    )
            else:
                object.__setattr__(self, "secret", env_secret)
        return self


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8090, ge=1024, le=65535)
    log_level: str = "INFO"


class ROS2Config(BaseModel):
    enabled: bool = True  # set False to run without ROS2 (tests, dev)
    service_timeout_sec: float = Field(default=5.0, ge=0.5, le=30.0)
    # LLMQuery blocks server-side on the LLM call itself; give it real headroom.
    llm_query_timeout_sec: float = Field(default=35.0, ge=5.0, le=120.0)
    # NavigateTo blocks until arrival or failure (node default 120s).
    navigate_timeout_sec: float = Field(default=130.0, ge=10.0, le=300.0)


class SessionConfig(BaseModel):
    """Patient-facing session lifecycle — the core PHI safety control.

    A patient session holds unsubmitted intake data in memory only. It is
    wiped on idle timeout, on explicit "done"/"start over", or on privacy
    mode failing to engage — never left for the next patient to see.
    """

    idle_timeout_sec: float = Field(default=90.0, ge=15.0, le=600.0)
    max_session_age_sec: float = Field(default=1800.0, ge=60.0)


class AuditConfig(BaseModel):
    db_path: Path = Field(default=Path("/tmp/bonbon/patient_kiosk/phi_audit.db"))
    max_events: int = Field(default=200_000, ge=1000)

    @model_validator(mode="after")
    def _ensure_dir(self) -> "AuditConfig":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return self


class RetentionConfig(BaseModel):
    """Retention/purge policy for submitted intake records. Hospitals set
    this per their own PDPA/HIPAA-equivalent policy — no default is a
    substitute for a real compliance review."""

    intake_retention_days: int = Field(default=30, ge=1)
    purge_check_interval_sec: float = Field(default=3600.0, ge=60.0)


class EncryptionConfig(BaseModel):
    """AES-256 key for the local patient data store. NEVER hardcoded."""

    key_hex: str = Field(default="")

    @model_validator(mode="after")
    def _require_key(self) -> "EncryptionConfig":
        if not self.key_hex:
            env_key = os.environ.get("BONBON_KIOSK_DATA_KEY", "")
            if not env_key:
                if os.environ.get("BONBON_TEST_MODE", "0") == "1":
                    object.__setattr__(self, "key_hex", secrets.token_hex(32))
                else:
                    raise ValueError(
                        "BONBON_KIOSK_DATA_KEY environment variable must be set "
                        "(32-byte hex key). Generate one with: openssl rand -hex 32"
                    )
            else:
                object.__setattr__(self, "key_hex", env_key)
        return self


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


class KioskAPIConfig(BaseModel):
    """Root configuration for the bonbon_patient_kiosk package."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    jwt: JWTConfig = Field(default_factory=JWTConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    ros2: ROS2Config = Field(default_factory=ROS2Config)
    session: SessionConfig = Field(default_factory=SessionConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    encryption: EncryptionConfig = Field(default_factory=EncryptionConfig)
    staff_users_db_path: Path = Field(default=Path("/tmp/bonbon/patient_kiosk/staff_users.db"))
    patient_data_db_path: Path = Field(default=Path("/tmp/bonbon/patient_kiosk/patient_data.db"))
    facility_labels_path: Path = Field(
        default=Path("/tmp/bonbon/patient_kiosk/facility_labels.json")
    )
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "KioskAPIConfig":
        return cls()

    @model_validator(mode="after")
    def _ensure_dirs(self) -> "KioskAPIConfig":
        self.staff_users_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.patient_data_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.facility_labels_path.parent.mkdir(parents=True, exist_ok=True)
        return self
