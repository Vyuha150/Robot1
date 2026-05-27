"""
bonbon_llm.personality
=======================
Response personality and TTS formatting layer.

Applied as the final transform after safety filtering and hallucination
checking, before text is dispatched to TTS.
"""

from bonbon_llm.personality.personality_layer import PersonalityLayer

__all__ = ["PersonalityLayer"]
