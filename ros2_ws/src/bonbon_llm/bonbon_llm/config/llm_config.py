"""
bonbon_llm.config.llm_config
=============================
Typed configuration hierarchy for the LLM + Response Generation Module.

All model names and API endpoints default to safe values that work out-of-the-box
with a local Ollama installation.  No secrets or external API keys are needed.

Parameter injection order:
  Python defaults → ROS2 declare_parameter / get_parameter (in from_ros_params)
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Ollama / LLM backend ──────────────────────────────────────────────────────


@dataclass
class OllamaConfig:
    """Connection and model settings for the local Ollama server."""

    base_url: str = "http://localhost:11434"
    model: str = "llama3.2:3b"  # pulled via: ollama pull llama3.2:3b
    timeout_sec: float = 30.0
    temperature: float = 0.4  # low = more deterministic / less hallucination
    max_tokens: int = 256  # keep responses concise for a service robot
    num_ctx: int = 4096  # context window (must fit prompt + RAG)

    def validate(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError(f"OllamaConfig.base_url must start with http(s)://: {self.base_url!r}")
        if self.temperature < 0.0 or self.temperature > 2.0:
            raise ValueError("OllamaConfig.temperature must be in [0, 2]")
        if self.max_tokens < 1:
            raise ValueError("OllamaConfig.max_tokens must be >= 1")


# ── RAG / retrieval ───────────────────────────────────────────────────────────


@dataclass
class RAGConfig:
    """Vector-store retrieval configuration."""

    backend: str = "chroma"  # "chroma" | "faiss" | "none"
    persist_dir: str = ""  # empty = in-memory (good for tests)
    collection_name: str = "bonbon_knowledge"
    embedding_model: str = "all-MiniLM-L6-v2"  # sentence-transformers model

    top_k: int = 5  # documents to retrieve
    similarity_threshold: float = 0.35  # below this → doc excluded
    max_context_tokens: int = 800  # hard cap on injected RAG text

    def validate(self) -> None:
        if self.backend not in ("chroma", "faiss", "none"):
            raise ValueError(f"RAGConfig.backend must be chroma|faiss|none, got {self.backend!r}")
        if not 0.0 <= self.similarity_threshold <= 1.0:
            raise ValueError("RAGConfig.similarity_threshold must be in [0, 1]")


# ── Safety filtering ──────────────────────────────────────────────────────────


@dataclass
class SafetyFilterConfig:
    """Controls which LLM-generated commands are blocked, flagged or permitted."""

    # Commands LLM must NEVER produce — blocked regardless of safety state.
    # These bypass the behavior engine and directly control hardware.
    blocked_patterns: list[str] = field(
        default_factory=lambda: [
            "cmd_vel",
            "geometry_msgs",
            "Twist",
            "publish.*velocity",
            "NavigateToPose",
            "nav2",
            "move_base",
            "set_goal",
            "GPIO",
            "servo.*angle",
            "direct.*motor",
            "PWM",
            r"os\.system",
            "subprocess",
            r"eval\(",
            r"exec\(",
        ]
    )

    # Commands requiring SafetyState.actuation_permitted before dispatch.
    risky_intent_classes: list[str] = field(
        default_factory=lambda: [
            "navigate_to",
            "serve_item",
            "approach_person",
        ]
    )

    # Minimum confidence to dispatch a risky command without extra confirmation.
    min_risky_confidence: float = 0.80

    # Words that should never appear in robot speech output (safety announcements
    # excepted — those come from bonbon_safety, not the LLM).
    forbidden_speech_words: list[str] = field(
        default_factory=lambda: [
            "emergency",
            "malfunction",
            "critical failure",
            "system error",
            "hardware fault",
        ]
    )


# ── Hallucination guard ───────────────────────────────────────────────────────


@dataclass
class HallucinationConfig:
    """Controls the grounding / hallucination-prevention layer."""

    enabled: bool = True
    min_grounding_score: float = 0.30  # below → flag as potentially hallucinated
    # Claims the LLM must NOT make about itself
    impossible_capability_phrases: list[str] = field(
        default_factory=lambda: [
            "i can fly",
            "i have arms",
            "i can carry more than",
            "i am a human",
            "i have a face",
            "i can see in the dark",
            "i know your name",
            "i remember you from last",
        ]
    )

    # If LLM invents facts not in RAG and confidence is below this, use fallback
    ungrounded_fallback_threshold: float = 0.50


# ── Robot personality ─────────────────────────────────────────────────────────


@dataclass
class PersonalityConfig:
    """Robot identity and response style."""

    name: str = "BonBon"
    role: str = "service robot at a café"
    tone: str = "friendly, concise, helpful"
    max_response_words: int = 40  # keep responses brief for spoken TTS
    language_adapt: bool = True  # mirror the user's language (EN/ZH/etc.)
    # Phrases appended occasionally to feel natural (randomly sampled)
    affirmations: list[str] = field(
        default_factory=lambda: [
            "Of course!",
            "Sure thing!",
            "Absolutely!",
            "Happy to help!",
            "Right away!",
            "Got it!",
            "No problem!",
        ]
    )


# ── Command authorization ─────────────────────────────────────────────────────


@dataclass
class AuthorizationConfig:
    """Command authorization settings."""

    require_safety_normal_for_navigation: bool = True
    require_actuation_permitted: bool = True
    authorization_timeout_sec: float = 5.0
    # intent classes that need confirmed Safety NORMAL before dispatch
    navigation_intent_classes: list[str] = field(
        default_factory=lambda: [
            "navigate_to",
            "navigate_to_goal",
            "approach_person",
        ]
    )
    actuation_intent_classes: list[str] = field(
        default_factory=lambda: [
            "serve_item",
        ]
    )


# ── Top-level config ──────────────────────────────────────────────────────────


@dataclass
class LLMConfig:
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    safety_filter: SafetyFilterConfig = field(default_factory=SafetyFilterConfig)
    hallucination: HallucinationConfig = field(default_factory=HallucinationConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    authorization: AuthorizationConfig = field(default_factory=AuthorizationConfig)

    # Node-level
    scene_publish_rate_hz: float = 5.0
    health_rate_hz: float = 1.0
    allow_degraded_startup: bool = False
    response_log_topic: str = "/llm/log"

    def validate(self) -> None:
        self.ollama.validate()
        self.rag.validate()

    def summary(self) -> str:
        return (
            f"model={self.ollama.model} "
            f"rag={self.rag.backend} "
            f"personality={self.personality.name} "
            f"hallucination_guard={self.hallucination.enabled}"
        )

    @classmethod
    def from_ros_params(cls, node) -> LLMConfig:
        """Build config from ROS2 parameter declarations."""

        def _get(name: str, default):
            node.declare_parameter(name, default)
            return node.get_parameter(name).value

        cfg = cls()

        # Ollama
        cfg.ollama.base_url = _get("ollama.base_url", "http://localhost:11434")
        cfg.ollama.model = _get("ollama.model", "llama3.2:3b")
        cfg.ollama.timeout_sec = _get("ollama.timeout_sec", 30.0)
        cfg.ollama.temperature = _get("ollama.temperature", 0.4)
        cfg.ollama.max_tokens = _get("ollama.max_tokens", 256)
        cfg.ollama.num_ctx = _get("ollama.num_ctx", 4096)

        # RAG
        cfg.rag.backend = _get("rag.backend", "chroma")
        cfg.rag.persist_dir = _get("rag.persist_dir", "")
        cfg.rag.collection_name = _get("rag.collection_name", "bonbon_knowledge")
        cfg.rag.embedding_model = _get("rag.embedding_model", "all-MiniLM-L6-v2")
        cfg.rag.top_k = _get("rag.top_k", 5)
        cfg.rag.similarity_threshold = _get("rag.similarity_threshold", 0.35)

        # Hallucination
        cfg.hallucination.enabled = _get("hallucination.enabled", True)
        cfg.hallucination.min_grounding_score = _get("hallucination.min_grounding_score", 0.30)

        # Personality
        cfg.personality.name = _get("personality.name", "BonBon")
        cfg.personality.max_response_words = _get("personality.max_response_words", 40)

        # Node
        cfg.health_rate_hz = _get("health_rate_hz", 1.0)
        cfg.allow_degraded_startup = _get("allow_degraded_startup", False)

        return cfg
