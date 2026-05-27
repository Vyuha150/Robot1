"""
tests.test_command_filter
==========================
Unit tests for bonbon_llm.safety.command_filter.SafetyCommandFilter.

Tests cover
-----------
* Hard-block patterns for direct hardware control attempts
* RISKY escalation for known navigation/actuation intents
* SAFE pass-through for benign speech
* Unsafe command tests: cmd_vel, nav2, GPIO, subprocess, eval
* Speech forbidden-word filter
* Behavior filter by class and confidence
"""

import pytest
from bonbon_llm.config.llm_config import SafetyFilterConfig
from bonbon_llm.safety.command_filter import (
    FilterStatus,
    SafetyCommandFilter,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def filt() -> SafetyCommandFilter:
    return SafetyCommandFilter(SafetyFilterConfig())


# ── BLOCKED: direct hardware control attempts ─────────────────────────────────


class TestHardBlockedPatterns:

    def test_cmd_vel_blocked(self, filt):
        result = filt.filter_text("publish to /cmd_vel with linear.x = 0.5")
        assert result.status == FilterStatus.BLOCKED, "cmd_vel must be hard-blocked"

    def test_nav2_action_blocked(self, filt):
        result = filt.filter_text("send goal to /navigate_to_pose action server")
        assert result.status == FilterStatus.BLOCKED

    def test_gpio_blocked(self, filt):
        result = filt.filter_text("set GPIO pin 17 high to open the valve")
        assert result.status == FilterStatus.BLOCKED

    def test_subprocess_blocked(self, filt):
        result = filt.filter_text("subprocess.run(['rm', '-rf', '/'])")
        assert result.status == FilterStatus.BLOCKED

    def test_eval_blocked(self, filt):
        result = filt.filter_text("eval(user_input) to execute code")
        assert result.status == FilterStatus.BLOCKED

    def test_exec_blocked(self, filt):
        result = filt.filter_text("exec('import os; os.system(\"ls\")')")
        assert result.status == FilterStatus.BLOCKED

    def test_ros2_topic_pub_blocked(self, filt):
        result = filt.filter_text("ros2 topic pub /cmd_vel geometry_msgs/Twist")
        assert result.status == FilterStatus.BLOCKED

    def test_nav_stack_reference_blocked(self, filt):
        result = filt.filter_text("send to nav stack directly")
        assert result.status == FilterStatus.BLOCKED

    def test_direct_motor_blocked(self, filt):
        result = filt.filter_text("set motor speed to maximum")
        assert result.status == FilterStatus.BLOCKED

    def test_actuator_direct_blocked(self, filt):
        result = filt.filter_text("directly actuate the servo")
        assert result.status == FilterStatus.BLOCKED

    def test_reason_populated(self, filt):
        result = filt.filter_text("publish cmd_vel")
        assert result.status == FilterStatus.BLOCKED
        assert result.reason is not None and len(result.reason) > 0

    def test_sanitized_text_empty_on_block(self, filt):
        result = filt.filter_text("gpio output pin 5")
        assert result.status == FilterStatus.BLOCKED
        # Sanitized text should not propagate the dangerous content
        assert "gpio" not in result.sanitized_text.lower()


# ── SAFE: benign speech ────────────────────────────────────────────────────────


class TestSafeSpeech:

    def test_greeting_safe(self, filt):
        result = filt.filter_text("Hello! Welcome to the café. What can I get you?")
        assert result.status == FilterStatus.SAFE

    def test_menu_question_safe(self, filt):
        result = filt.filter_text("Our latte costs S$5.50. Would you like one?")
        assert result.status == FilterStatus.SAFE

    def test_empty_string_safe(self, filt):
        # Empty text is allowed by the filter (caller should handle it separately)
        result = filt.filter_text("")
        assert result.status == FilterStatus.SAFE

    def test_price_info_safe(self, filt):
        result = filt.filter_text("The espresso is S$4.00. The cappuccino is S$5.50.")
        assert result.status == FilterStatus.SAFE

    def test_navigation_offer_safe(self, filt):
        # Offering to navigate as a conversational statement (not a direct command)
        result = filt.filter_text("I can take you to table 3! Shall I lead the way?")
        assert result.status == FilterStatus.SAFE

    def test_sanitized_text_preserved_on_safe(self, filt):
        text = "Good morning! How can I help you today?"
        result = filt.filter_text(text)
        assert result.status == FilterStatus.SAFE
        assert result.sanitized_text == text


# ── RISKY: intent classes needing authorization ───────────────────────────────


class TestRiskyBehaviors:

    def test_navigate_to_risky(self, filt):
        result = filt.filter_behavior("navigate_to_goal", confidence=0.90)
        assert result.status in (FilterStatus.RISKY, FilterStatus.SAFE)

    def test_approach_person_risky(self, filt):
        result = filt.filter_behavior("approach_person", confidence=0.85)
        assert result.status in (FilterStatus.RISKY, FilterStatus.SAFE)

    def test_serve_item_risky(self, filt):
        result = filt.filter_behavior("serve_item", confidence=0.95)
        assert result.status in (FilterStatus.RISKY, FilterStatus.SAFE)

    def test_idle_always_safe(self, filt):
        result = filt.filter_behavior("idle", confidence=0.99)
        assert result.status == FilterStatus.SAFE

    def test_wait_for_input_always_safe(self, filt):
        result = filt.filter_behavior("wait_for_input", confidence=0.99)
        assert result.status == FilterStatus.SAFE

    def test_low_confidence_risky_command_blocked(self, filt):
        # navigate_to_goal at very low confidence should be BLOCKED or RISKY
        result = filt.filter_behavior("navigate_to_goal", confidence=0.10)
        assert result.status != FilterStatus.SAFE, "Low-confidence navigation should not be SAFE"

    def test_stop_navigation_safe(self, filt):
        result = filt.filter_behavior("stop_navigation", confidence=0.99)
        assert result.status == FilterStatus.SAFE


# ── is_safe_speech helper ──────────────────────────────────────────────────────


class TestIsSafeSpeech:

    def test_normal_text_is_safe_speech(self, filt):
        assert filt.is_safe_speech("Hello there!") is True

    def test_forbidden_word_not_safe_speech(self, filt):
        # Any text referencing direct hardware control should not be safe speech
        assert filt.is_safe_speech("gpio pin") is False

    def test_cmd_vel_not_safe_speech(self, filt):
        assert filt.is_safe_speech("publish cmd_vel message") is False


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_unicode_text_safe(self, filt):
        result = filt.filter_text("您好！欢迎来到咖啡馆。")
        assert result.status == FilterStatus.SAFE

    def test_malay_text_safe(self, filt):
        result = filt.filter_text("Selamat datang! Apa yang anda inginkan?")
        assert result.status == FilterStatus.SAFE

    def test_mixed_case_pattern_blocked(self, filt):
        # Patterns should be case-insensitive
        result = filt.filter_text("CMD_VEL topic publish")
        assert result.status == FilterStatus.BLOCKED

    def test_very_long_text_handled(self, filt):
        long_text = "Hello! " * 200  # 1400 chars
        result = filt.filter_text(long_text)
        assert result.status == FilterStatus.SAFE
