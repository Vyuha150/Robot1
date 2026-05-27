"""
bonbon_perception_ai.config.perception_config
=============================================
Typed configuration hierarchy for the Perception + AI module.

All paths default to empty strings (runtime-injected via ROS2 params).
No secrets, no hardcoded file paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Fusion config ─────────────────────────────────────────────────────────────


@dataclass
class FusionConfig:
    """Controls multi-modal fusion and staleness detection."""

    # Per-modality staleness timeout (seconds).
    # A modality is marked STALE when no update has arrived within this window.
    objects_stale_sec: float = 2.0
    persons_stale_sec: float = 2.0
    speech_stale_sec: float = 8.0  # speech is infrequent by design
    pose_stale_sec: float = 5.0
    nav_stale_sec: float = 5.0

    # When confidence of two conflicting inputs differs by > this, take the
    # higher-confidence one.  Below this → "conflicting" flag is set.
    conflict_confidence_gap: float = 0.2

    # Minimum per-object/person confidence to include in the fusion context.
    min_object_confidence: float = 0.40
    min_person_confidence: float = 0.50

    def validate(self) -> None:
        for name, val in [
            ("objects_stale_sec", self.objects_stale_sec),
            ("persons_stale_sec", self.persons_stale_sec),
            ("speech_stale_sec", self.speech_stale_sec),
            ("pose_stale_sec", self.pose_stale_sec),
            ("nav_stale_sec", self.nav_stale_sec),
        ]:
            if val <= 0:
                raise ValueError(f"FusionConfig.{name} must be > 0")


# ── Scene analysis config ─────────────────────────────────────────────────────


@dataclass
class SceneConfig:
    """Controls SceneAnalyzer behaviour."""

    # Distance thresholds
    near_person_threshold_m: float = 2.0  # closer → spatial_context = "near_person"
    interaction_proximity_m: float = 1.5  # closer → activity = "serving/interacting"
    crowded_threshold: int = 3  # ≥ N persons → is_crowded = True

    # Event detection: ignore scene changes smaller than this time gap
    event_debounce_sec: float = 0.5

    def validate(self) -> None:
        if self.crowded_threshold < 1:
            raise ValueError("SceneConfig.crowded_threshold must be >= 1")


# ── Intent engine config ──────────────────────────────────────────────────────


@dataclass
class IntentConfig:
    """Controls intent classification backend and thresholds."""

    backend: str = "rule_based"  # "rule_based" | "langchain"

    # LangChain settings — only used when backend="langchain".
    # API key MUST be injected at runtime, never hardcoded.
    langchain_model: str = "gpt-3.5-turbo"
    langchain_api_key: str = ""  # set via ROS2 param or env var OPENAI_API_KEY
    langchain_timeout_sec: float = 5.0

    # Below this confidence → is_ambiguous = True
    intent_confidence_threshold: float = 0.55

    # What to do when intent is ambiguous:
    #   "clarify"     → publish is_ambiguous=True with fallback_response text
    #   "best_guess"  → publish best guess with is_ambiguous=True
    #   "ignore"      → do not publish anything
    ambiguity_policy: str = "clarify"

    def validate(self) -> None:
        if self.backend not in ("rule_based", "langchain"):
            raise ValueError(
                f"IntentConfig.backend must be 'rule_based' or 'langchain', got {self.backend!r}"
            )
        if self.ambiguity_policy not in ("clarify", "best_guess", "ignore"):
            raise ValueError(f"IntentConfig.ambiguity_policy invalid: {self.ambiguity_policy!r}")
        if not 0.0 < self.intent_confidence_threshold < 1.0:
            raise ValueError("IntentConfig.intent_confidence_threshold must be in (0, 1)")


# ── Risk assessor config ──────────────────────────────────────────────────────


@dataclass
class RiskConfig:
    """Controls RiskAssessor thresholds."""

    # Person proximity thresholds
    critical_proximity_m: float = 0.40  # → SEVERITY_CRITICAL
    high_proximity_m: float = 0.70  # → SEVERITY_HIGH
    caution_proximity_m: float = 1.20  # → SEVERITY_MEDIUM

    # Navigation
    nav_uncertainty_risk: bool = True  # raise risk when navigating with HIGH uncertainty
    crowded_severity: str = "LOW"  # severity when scene is crowded

    def validate(self) -> None:
        if not (self.critical_proximity_m < self.high_proximity_m < self.caution_proximity_m):
            raise ValueError(
                "RiskConfig proximity thresholds must satisfy: " "critical < high < caution"
            )


# ── Memory config ─────────────────────────────────────────────────────────────


@dataclass
class MemoryConfig:
    """Controls FAISS + SQLite memory backends."""

    # SQLite database path.  Empty string → in-memory DB (useful for tests).
    db_path: str = ""

    # FAISS / vector store
    vector_dim: int = 32  # must match SceneEmbedding.DIM
    max_episodes: int = 10_000  # oldest evicted when exceeded

    # Retention
    episode_ttl_days: float = 7.0  # purge scene episodes older than this

    # Privacy
    privacy_anonymize_persons: bool = False  # replace person IDs with anonymous UUIDs
    privacy_store_faces: bool = False  # whether to persist face_id strings

    def validate(self) -> None:
        if self.vector_dim <= 0:
            raise ValueError("MemoryConfig.vector_dim must be > 0")
        if self.max_episodes <= 0:
            raise ValueError("MemoryConfig.max_episodes must be > 0")
        if self.episode_ttl_days <= 0:
            raise ValueError("MemoryConfig.episode_ttl_days must be > 0")


# ── Privacy config ────────────────────────────────────────────────────────────


@dataclass
class PrivacyConfig:
    anonymize_persons: bool = False
    store_faces: bool = False
    suppress_speaker_id: bool = False
    max_memory_retention_days: float = 7.0


# ── Top-level config ──────────────────────────────────────────────────────────


@dataclass
class PerceptionAIConfig:
    fusion: FusionConfig = field(default_factory=FusionConfig)
    scene: SceneConfig = field(default_factory=SceneConfig)
    intent: IntentConfig = field(default_factory=IntentConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)

    # Node-level options
    scene_publish_rate_hz: float = 10.0
    health_rate_hz: float = 1.0
    allow_degraded_startup: bool = False

    def validate(self) -> None:
        self.fusion.validate()
        self.scene.validate()
        self.intent.validate()
        self.risk.validate()
        self.memory.validate()

    def summary(self) -> str:
        return (
            f"intent_backend={self.intent.backend} "
            f"memory_db={self.memory.db_path or ':memory:'} "
            f"privacy_anon={self.privacy.anonymize_persons}"
        )

    # ── ROS2 parameter loader ─────────────────────────────────────────────────

    @classmethod
    def from_ros_params(cls, node) -> PerceptionAIConfig:
        """Build config from ROS2 declare_parameter / get_parameter calls."""

        def _get(name: str, default):
            node.declare_parameter(name, default)
            return node.get_parameter(name).value

        cfg = cls()

        # Fusion
        cfg.fusion.objects_stale_sec = _get("fusion.objects_stale_sec", 2.0)
        cfg.fusion.persons_stale_sec = _get("fusion.persons_stale_sec", 2.0)
        cfg.fusion.speech_stale_sec = _get("fusion.speech_stale_sec", 8.0)
        cfg.fusion.pose_stale_sec = _get("fusion.pose_stale_sec", 5.0)
        cfg.fusion.nav_stale_sec = _get("fusion.nav_stale_sec", 5.0)
        cfg.fusion.min_object_confidence = _get("fusion.min_object_confidence", 0.40)
        cfg.fusion.min_person_confidence = _get("fusion.min_person_confidence", 0.50)

        # Scene
        cfg.scene.near_person_threshold_m = _get("scene.near_person_threshold_m", 2.0)
        cfg.scene.interaction_proximity_m = _get("scene.interaction_proximity_m", 1.5)
        cfg.scene.crowded_threshold = _get("scene.crowded_threshold", 3)
        cfg.scene.event_debounce_sec = _get("scene.event_debounce_sec", 0.5)

        # Intent
        cfg.intent.backend = _get("intent.backend", "rule_based")
        cfg.intent.langchain_model = _get("intent.langchain_model", "gpt-3.5-turbo")
        cfg.intent.langchain_api_key = _get("intent.langchain_api_key", "")
        cfg.intent.intent_confidence_threshold = _get("intent.intent_confidence_threshold", 0.55)
        cfg.intent.ambiguity_policy = _get("intent.ambiguity_policy", "clarify")

        # Risk
        cfg.risk.critical_proximity_m = _get("risk.critical_proximity_m", 0.40)
        cfg.risk.high_proximity_m = _get("risk.high_proximity_m", 0.70)
        cfg.risk.caution_proximity_m = _get("risk.caution_proximity_m", 1.20)

        # Memory
        cfg.memory.db_path = _get("memory.db_path", "")
        cfg.memory.max_episodes = _get("memory.max_episodes", 10000)
        cfg.memory.episode_ttl_days = _get("memory.episode_ttl_days", 7.0)
        cfg.memory.privacy_anonymize_persons = _get("memory.privacy_anonymize_persons", False)
        cfg.memory.privacy_store_faces = _get("memory.privacy_store_faces", False)

        # Privacy
        cfg.privacy.anonymize_persons = _get("privacy.anonymize_persons", False)
        cfg.privacy.store_faces = _get("privacy.store_faces", False)
        cfg.privacy.suppress_speaker_id = _get("privacy.suppress_speaker_id", False)
        cfg.privacy.max_memory_retention_days = _get("privacy.max_memory_retention_days", 7.0)

        # Node
        cfg.scene_publish_rate_hz = _get("scene_publish_rate_hz", 10.0)
        cfg.health_rate_hz = _get("health_rate_hz", 1.0)
        cfg.allow_degraded_startup = _get("allow_degraded_startup", False)

        return cfg
