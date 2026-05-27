"""
tests.test_personality_layer
==============================
Unit tests for bonbon_llm.personality.personality_layer.PersonalityLayer.

Tests cover
-----------
* Markdown stripping (bold, italic, backtick, headers, bullet lists)
* Word-limit enforcement with sentence-boundary truncation
* Affirmation prepend
* Name replacement ("the robot" → configured name)
* TTS formatting:  S$ → "Singapore dollars"
                   m/s → "metres per second"
                   kg  → "kilograms"
                   cm  → "centimetres"
* Language detection does not crash (ZH, MS, EN)
* Empty input handled gracefully
"""

from bonbon_llm.config.llm_config import PersonalityConfig
from bonbon_llm.personality.personality_layer import PersonalityLayer

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _layer(
    name: str = "BonBon",
    max_words: int = 40,
    affirmations: list = None,
) -> PersonalityLayer:
    cfg = PersonalityConfig(
        name=name,
        max_response_words=max_words,
        affirmations=affirmations or ["Sure!", "Of course!", "Absolutely!"],
    )
    return PersonalityLayer(cfg)


# ── Markdown stripping ─────────────────────────────────────────────────────────


class TestMarkdownStripping:

    def test_bold_stripped(self):
        layer = _layer()
        result = layer.apply("This is **bold** text.")
        assert "**" not in result
        assert "bold" in result

    def test_italic_stripped(self):
        layer = _layer()
        result = layer.apply("This is *italic* text.")
        assert "*" not in result
        assert "italic" in result

    def test_backtick_stripped(self):
        layer = _layer()
        result = layer.apply("Use `cmd_vel` for motion.")
        assert "`" not in result

    def test_header_stripped(self):
        layer = _layer()
        result = layer.apply("## Menu\nLatte: S$5.00")
        assert "##" not in result
        assert "Latte" in result

    def test_bullet_list_stripped(self):
        layer = _layer()
        result = layer.apply("Items:\n- Latte\n- Espresso\n- Cappuccino")
        assert "- " not in result
        assert "Latte" in result

    def test_numbered_list_stripped(self):
        layer = _layer()
        result = layer.apply("1. First\n2. Second\n3. Third")
        assert "1." not in result
        assert "First" in result

    def test_plain_text_unchanged(self):
        layer = _layer()
        text = "Hello! Welcome to the café."
        result = layer.apply(text)
        assert result == text

    def test_link_stripped(self):
        layer = _layer()
        result = layer.apply("Visit [our website](https://example.com) for more.")
        assert "[" not in result
        assert "](" not in result


# ── Word-limit enforcement ────────────────────────────────────────────────────


class TestWordLimitEnforcement:

    def test_short_text_unchanged(self):
        layer = _layer(max_words=40)
        text = "Hello! The latte is S$5.00."
        result = layer.apply(text)
        # No truncation for short text
        assert "Hello" in result

    def test_long_text_truncated(self):
        layer = _layer(max_words=10)
        text = "This is a very long response that has many words in it. " * 5
        result = layer.apply(text)
        assert len(result.split()) <= 12  # slight tolerance for sentence boundary

    def test_truncation_ends_at_sentence_boundary(self):
        layer = _layer(max_words=15)
        text = "The latte costs five dollars. The cappuccino costs six dollars. The espresso is four dollars."
        result = layer.apply(text)
        # Should end at a sentence boundary (. ! ?)
        assert result.endswith(".") or result.endswith("!") or result.endswith("?")

    def test_truncation_adds_period_if_no_boundary(self):
        layer = _layer(max_words=5)
        text = "Hello world foo bar baz qux quux"
        result = layer.apply(text)
        # Result should end with a period if no sentence boundary found
        assert result.endswith(".")

    def test_exact_word_limit_not_truncated(self):
        layer = _layer(max_words=5)
        text = "One two three four five."
        result = layer.apply(text)
        assert "One" in result


# ── Affirmation prepend ───────────────────────────────────────────────────────


class TestAffirmationPrepend:

    def test_affirmation_prepended_when_requested(self):
        layer = _layer(affirmations=["Sure!"])
        result = layer.apply("The latte is S$5.00.", use_affirmation=True)
        assert result.startswith("Sure!")

    def test_no_affirmation_without_flag(self):
        layer = _layer(affirmations=["Sure!", "Of course!"])
        result = layer.apply("The latte is S$5.00.", use_affirmation=False)
        assert not result.startswith("Sure!")
        assert not result.startswith("Of course!")

    def test_empty_affirmation_list_no_crash(self):
        layer = _layer(affirmations=[])
        result = layer.apply("Hello!", use_affirmation=True)
        assert isinstance(result, str)
        assert len(result) > 0


# ── Name replacement ──────────────────────────────────────────────────────────


class TestNameReplacement:

    def test_the_robot_replaced_with_name(self):
        layer = _layer(name="BonBon")
        result = layer.apply("The robot will bring your order shortly.")
        assert "the robot" not in result.lower()
        assert "BonBon" in result

    def test_name_preserved_if_already_correct(self):
        layer = _layer(name="BonBon")
        result = layer.apply("BonBon will bring your order shortly.")
        assert "BonBon" in result

    def test_custom_name_used(self):
        layer = _layer(name="Robo")
        result = layer.apply("The robot is at your service.")
        assert "Robo" in result


# ── TTS formatting ─────────────────────────────────────────────────────────────


class TestTTSFormatting:

    def test_sgd_expanded(self):
        layer = _layer()
        result = layer.apply("The latte costs S$5.50.")
        assert "Singapore dollars" in result
        assert "S$" not in result

    def test_mps_expanded(self):
        layer = _layer()
        result = layer.apply("I travel at 0.5 m/s.")
        assert "metres per second" in result.lower()
        assert "m/s" not in result

    def test_kg_expanded(self):
        layer = _layer()
        result = layer.apply("I can carry up to 2 kg.")
        assert "kilograms" in result.lower()
        assert "kg" not in result

    def test_cm_expanded(self):
        layer = _layer()
        result = layer.apply("I stop at 40 cm from obstacles.")
        assert "centimetres" in result.lower()
        assert "cm" not in result

    def test_format_for_tts_standalone(self):
        layer = _layer()
        result = layer.format_for_tts("Price: S$4.50")
        assert "Singapore dollars" in result


# ── Language adaptation ────────────────────────────────────────────────────────


class TestLanguageAdaptation:

    def test_chinese_text_no_crash(self):
        layer = _layer()
        result = layer.apply("您好！拿铁咖啡是五新元五角。", user_text="我想要一杯拿铁")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_malay_text_no_crash(self):
        layer = _layer()
        result = layer.apply("Latte ialah S$5.50.", user_text="Saya nak latte tolong")
        assert isinstance(result, str)

    def test_english_text_no_crash(self):
        layer = _layer()
        result = layer.apply("Hello! Welcome to the café.", user_text="What can you do?")
        assert isinstance(result, str)


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_string_no_crash(self):
        layer = _layer()
        result = layer.apply("")
        assert isinstance(result, str)

    def test_whitespace_only_no_crash(self):
        layer = _layer()
        result = layer.apply("   \n\n   ")
        assert isinstance(result, str)

    def test_apply_strips_leading_trailing_whitespace(self):
        layer = _layer()
        result = layer.apply("  Hello world.  ")
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_multiple_newlines_collapsed(self):
        layer = _layer()
        result = layer.apply("Hello.\n\n\nGoodbye.")
        assert "\n\n" not in result
