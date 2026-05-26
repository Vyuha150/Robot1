"""
bonbon_perception_ai
====================
Perception + AI module for the Bonbon service robot.

Pipeline
--------
MultimodalFusion → SceneAnalyzer → IntentEngine → RiskAssessor
    → BehaviorRecommender → MemoryManager

Quick import path for the most commonly used types:

    from bonbon_perception_ai import (
        PerceptionAIConfig,
        MultimodalFusion, FusionContext,
        SceneAnalyzer, SceneSnapshot,
        IntentEngine, UserIntent,
        RiskAssessor, RiskEvent,
        BehaviorRecommender, BehaviorRecommendation,
        MemoryManager,
    )
"""
from bonbon_perception_ai.config.perception_config import PerceptionAIConfig

from bonbon_perception_ai.fusion.multimodal_fusion import MultimodalFusion
from bonbon_perception_ai.fusion.types import (
    FusionContext,
    ObjectObservation,
    PersonObservation,
    SpeechInput,
    RobotPose,
    NavStatus,
)

from bonbon_perception_ai.understanding.scene_analyzer import (
    SceneAnalyzer,
    SceneSnapshot,
    ContextEvent,
)
from bonbon_perception_ai.understanding.intent_engine import (
    IntentEngine,
    UserIntent,
    IntentSlot,
)
from bonbon_perception_ai.understanding.risk_assessor import (
    RiskAssessor,
    RiskEvent,
)
from bonbon_perception_ai.understanding.behavior_recommender import (
    BehaviorRecommender,
    BehaviorRecommendation,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_HIGH,
    PRIORITY_URGENT,
)
from bonbon_perception_ai.memory.memory_manager import MemoryManager

__version__ = "1.0.0"

__all__ = [
    # Config
    "PerceptionAIConfig",
    # Fusion
    "MultimodalFusion",
    "FusionContext",
    "ObjectObservation",
    "PersonObservation",
    "SpeechInput",
    "RobotPose",
    "NavStatus",
    # Understanding
    "SceneAnalyzer",
    "SceneSnapshot",
    "ContextEvent",
    "IntentEngine",
    "UserIntent",
    "IntentSlot",
    "RiskAssessor",
    "RiskEvent",
    "BehaviorRecommender",
    "BehaviorRecommendation",
    "PRIORITY_LOW",
    "PRIORITY_NORMAL",
    "PRIORITY_HIGH",
    "PRIORITY_URGENT",
    # Memory
    "MemoryManager",
]
