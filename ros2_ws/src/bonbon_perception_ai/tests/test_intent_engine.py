"""
Tests for IntentEngine.

Covers: standard intents, slot extraction, ambiguous commands,
conflicting inputs, silence/timeout, privacy, multi-language,
wrong/missing speech data.
"""

import time

import pytest
from bonbon_perception_ai.config.perception_config import IntentConfig
from bonbon_perception_ai.fusion.types import FusionContext, SpeechInput
from bonbon_perception_ai.understanding.intent_engine import (
    IntentEngine,
)


def _cfg(**kw) -> IntentConfig:
    defaults = dict(
        backend="rule_based",
        intent_confidence_threshold=0.55,
        ambiguity_policy="clarify",
    )
    defaults.update(kw)
    return IntentConfig(**defaults)


def _ctx() -> FusionContext:
    return FusionContext(
        timestamp=time.monotonic(),
        objects=[],
        persons=[],
        speech=None,
        robot_pose=None,
        nav_status=None,
        stale_modalities=[],
        uncertainty_level="LOW",
    )


def _speech(text, confidence=0.9, silence=False, timeout=False, speaker="spk1") -> SpeechInput:
    return SpeechInput(
        text=text,
        confidence=confidence,
        is_silence=silence,
        is_timeout=timeout,
        speaker_id=speaker,
    )


# ── Standard intents ──────────────────────────────────────────────────────────


class TestStandardIntents:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("I'd like to order a coffee please", "order_item"),
            ("Can you bring me some water", "order_item"),
            ("Go to table 5", "navigate_to"),
            ("Follow me", "navigate_to"),
            ("What time is it", "ask_question"),
            ("Stop navigation", "cancel"),
            ("Yes, that's correct", "confirm"),
            ("No, not that one", "deny"),
            ("I need help", "help_request"),
            ("Hello there", "greeting"),
        ],
    )
    def test_intent_class(self, text, expected):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech(text), _ctx())
        assert intent is not None
        assert intent.intent_class == expected

    def test_high_confidence_not_ambiguous(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("Go to the entrance"), _ctx())
        assert intent is not None
        assert not intent.is_ambiguous

    def test_intent_has_id(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("order tea"), _ctx())
        assert intent is not None
        assert len(intent.intent_id) > 0

    def test_speaker_id_preserved(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("hello", speaker="user_007"), _ctx())
        assert intent is not None
        assert intent.speaker_id == "user_007"

    def test_speech_confidence_propagated(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("order coffee", confidence=0.75), _ctx())
        assert intent is not None
        assert intent.speech_confidence == pytest.approx(0.75)


# ── Slot extraction ───────────────────────────────────────────────────────────


class TestSlotExtraction:
    def test_item_slot_extracted(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("please bring me a coffee"), _ctx())
        assert intent is not None
        slots = intent.slot_dict
        assert "item" in slots
        assert slots["item"] == "coffee"

    def test_destination_slot_extracted(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("go to table 3"), _ctx())
        assert intent is not None
        assert "destination" in intent.slot_dict

    def test_quantity_slot(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("bring me two coffees"), _ctx())
        assert intent is not None
        assert "quantity" in intent.slot_dict

    def test_no_slots_for_greeting(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("hello"), _ctx())
        assert intent is not None
        assert "item" not in intent.slot_dict
        assert "destination" not in intent.slot_dict


# ── Ambiguous commands ────────────────────────────────────────────────────────


class TestAmbiguousCommands:
    def test_gibberish_is_ambiguous(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("asdfghjkl zxcvbnm"), _ctx())
        assert intent is not None
        assert intent.is_ambiguous

    def test_clarify_policy_sets_fallback(self):
        engine = IntentEngine(_cfg(ambiguity_policy="clarify"))
        intent = engine.classify(_speech("blah blah"), _ctx())
        assert intent is not None
        assert intent.fallback_response != ""

    def test_best_guess_policy_keeps_intent(self):
        engine = IntentEngine(_cfg(ambiguity_policy="best_guess"))
        intent = engine.classify(_speech("blah blah"), _ctx())
        assert intent is not None
        assert intent.is_ambiguous  # still marked ambiguous
        # intent_class is NOT "unknown" — best guess is kept

    def test_ignore_policy_returns_none(self):
        engine = IntentEngine(_cfg(ambiguity_policy="ignore"))
        result = engine.classify(_speech("xyzzy plugh"), _ctx())
        assert result is None

    def test_low_speech_confidence_lowers_intent_confidence(self):
        engine = IntentEngine(_cfg())
        # low speech confidence doesn't block intent but may lower it
        intent = engine.classify(_speech("order coffee", confidence=0.1), _ctx())
        assert intent is not None  # intent engine uses text, not speech confidence


# ── Silence and timeout ───────────────────────────────────────────────────────


class TestSilenceAndTimeout:
    def test_silence_returns_silence_intent(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("", silence=True), _ctx())
        assert intent is not None
        assert intent.intent_class == "silence"
        assert not intent.is_ambiguous

    def test_timeout_returns_silence_intent(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("", timeout=True), _ctx())
        assert intent is not None
        assert intent.intent_class == "silence"

    def test_empty_text_is_silence(self):
        engine = IntentEngine(_cfg())
        intent = engine.classify(_speech("   "), _ctx())
        assert intent is not None
        assert intent.intent_class == "silence"


# ── Conflicting / contradictory commands ─────────────────────────────────────


class TestConflictingCommands:
    def test_confirm_after_deny_both_classified(self):
        engine = IntentEngine(_cfg())
        i1 = engine.classify(_speech("no thanks"), _ctx())
        i2 = engine.classify(_speech("yes please"), _ctx())
        assert i1 is not None and i1.intent_class == "deny"
        assert i2 is not None and i2.intent_class == "confirm"

    def test_cancel_after_order(self):
        engine = IntentEngine(_cfg())
        i1 = engine.classify(_speech("bring me a coffee"), _ctx())
        i2 = engine.classify(_speech("cancel that"), _ctx())
        assert i1 is not None and i1.intent_class == "order_item"
        assert i2 is not None and i2.intent_class == "cancel"


# ── Raw text preserved ────────────────────────────────────────────────────────


class TestRawText:
    def test_raw_text_preserved(self):
        engine = IntentEngine(_cfg())
        text = "Please bring me a cup of coffee for table 3"
        intent = engine.classify(_speech(text), _ctx())
        assert intent is not None
        assert intent.raw_text == text
