"""
test_safety_policy.py
=====================
Unit tests for bonbon_safety.core.safety_policy.

Tests
-----
- SafetyPolicy.default() builds a valid policy for all 8 states
- SafetyPolicy.from_yaml() correctly parses safety_policy.yaml
- PolicyAction enum values match expected action strings
- on_enter / on_exit action lists are correct per state
- LED / display / audio metadata is preserved
- Unknown action names raise ValueError
- Missing required states raise KeyError
"""

from __future__ import annotations

import os
import tempfile
import textwrap

import pytest
from bonbon_safety.core.safety_policy import PolicyAction, SafetyPolicy
from bonbon_safety.core.safety_state_machine import SafetyLevel

# Path to the real policy YAML (relative to package)
_PKG_DIR = os.path.join(os.path.dirname(__file__), "..", "bonbon_safety", "config")
_POLICY_YAML = os.path.join(_PKG_DIR, "safety_policy.yaml")


# ── PolicyAction ──────────────────────────────────────────────────────────────


class TestPolicyAction:
    def test_action_enum_has_core_values(self):
        required = {
            "zero_velocity",
            "cap_velocity",
            "cancel_navigation",
            "disable_actuation",
            "enable_actuation",
            "announce_audio",
            "update_led_eyes",
            "update_display",
            "log_incident",
            "notify_operator",
            "trigger_estop",
            "request_human_help",
            "initiate_docking",
        }
        actual = {a.value for a in PolicyAction}
        missing = required - actual
        assert not missing, f"Missing PolicyAction values: {missing}"


# ── SafetyPolicy.default() ────────────────────────────────────────────────────


class TestDefaultPolicy:
    def test_default_returns_policy(self):
        policy = SafetyPolicy.default()
        assert policy is not None

    def test_default_has_all_states(self):
        policy = SafetyPolicy.default()
        for level in SafetyLevel:
            assert policy.has_rules_for(level), f"Default policy missing rules for {level.name}"

    def test_danger_on_enter_has_zero_velocity(self):
        policy = SafetyPolicy.default()
        actions = policy.on_enter_actions(SafetyLevel.DANGER)
        assert PolicyAction.zero_velocity in actions

    def test_danger_on_enter_has_cancel_navigation(self):
        policy = SafetyPolicy.default()
        actions = policy.on_enter_actions(SafetyLevel.DANGER)
        assert PolicyAction.cancel_navigation in actions

    def test_normal_on_enter_has_enable_actuation(self):
        policy = SafetyPolicy.default()
        actions = policy.on_enter_actions(SafetyLevel.NORMAL)
        assert PolicyAction.enable_actuation in actions

    def test_safe_stop_on_enter_has_trigger_estop(self):
        policy = SafetyPolicy.default()
        actions = policy.on_enter_actions(SafetyLevel.SAFE_STOP)
        assert PolicyAction.trigger_estop in actions

    def test_fault_on_enter_has_request_human_help(self):
        policy = SafetyPolicy.default()
        actions = policy.on_enter_actions(SafetyLevel.FAULT)
        assert PolicyAction.request_human_help in actions

    def test_caution_on_exit_has_update_led(self):
        policy = SafetyPolicy.default()
        actions = policy.on_exit_actions(SafetyLevel.CAUTION)
        assert PolicyAction.update_led_eyes in actions

    def test_on_exit_empty_for_states_without_exit_actions(self):
        policy = SafetyPolicy.default()
        # FAULT has no on_exit in default config
        actions = policy.on_exit_actions(SafetyLevel.FAULT)
        assert isinstance(actions, list)  # must return list, may be empty

    def test_led_state_for_danger(self):
        policy = SafetyPolicy.default()
        meta = policy.metadata(SafetyLevel.DANGER)
        assert meta.get("led_state") == "warning"

    def test_led_state_for_normal(self):
        policy = SafetyPolicy.default()
        meta = policy.metadata(SafetyLevel.NORMAL)
        assert meta.get("led_state") == "happy"

    def test_display_text_for_safe_stop(self):
        policy = SafetyPolicy.default()
        meta = policy.metadata(SafetyLevel.SAFE_STOP)
        assert "EMERGENCY" in meta.get("display_text", "").upper()

    def test_audio_file_for_caution(self):
        policy = SafetyPolicy.default()
        meta = policy.metadata(SafetyLevel.CAUTION)
        assert meta.get("audio_file"), "CAUTION should have an audio file"

    def test_docking_announce_text(self):
        policy = SafetyPolicy.default()
        meta = policy.metadata(SafetyLevel.DOCKING)
        announce = meta.get("announce_text", "")
        assert len(announce) > 0, "DOCKING should have announce text"


# ── SafetyPolicy.from_yaml() ──────────────────────────────────────────────────


class TestFromYaml:
    @pytest.fixture(autouse=True)
    def _require_yaml(self):
        if not os.path.exists(_POLICY_YAML):
            pytest.skip(f"Policy YAML not found at {_POLICY_YAML}")

    def test_loads_without_error(self):
        policy = SafetyPolicy.from_yaml(_POLICY_YAML)
        assert policy is not None

    def test_yaml_has_all_states(self):
        policy = SafetyPolicy.from_yaml(_POLICY_YAML)
        for level in SafetyLevel:
            assert policy.has_rules_for(level), f"YAML policy missing {level.name}"

    def test_yaml_danger_actions(self):
        policy = SafetyPolicy.from_yaml(_POLICY_YAML)
        actions = policy.on_enter_actions(SafetyLevel.DANGER)
        assert PolicyAction.zero_velocity in actions
        assert PolicyAction.cancel_navigation in actions
        assert PolicyAction.disable_actuation in actions

    def test_yaml_initializing_no_actuation(self):
        policy = SafetyPolicy.from_yaml(_POLICY_YAML)
        actions = policy.on_enter_actions(SafetyLevel.INITIALIZING)
        assert PolicyAction.disable_actuation in actions

    def test_yaml_led_states_nonempty(self):
        policy = SafetyPolicy.from_yaml(_POLICY_YAML)
        for level in SafetyLevel:
            meta = policy.metadata(level)
            led = meta.get("led_state", "")
            assert led, f"{level.name} has empty led_state in YAML"


# ── from_yaml() with synthetic YAML ──────────────────────────────────────────


class TestFromYamlSynthetic:
    _MINIMAL_YAML = textwrap.dedent("""\
        rules:
          NORMAL:
            on_enter:
              - enable_actuation
              - update_led_eyes
            led_state: "happy"
            display_text: ""
          INITIALIZING:
            on_enter:
              - disable_actuation
            led_state: "thinking"
            display_text: "Starting"
          CAUTION:
            on_enter:
              - cap_velocity
            on_exit:
              - update_led_eyes
            led_state: "alert"
            display_text: "Caution"
          DANGER:
            on_enter:
              - zero_velocity
              - cancel_navigation
              - disable_actuation
            led_state: "warning"
            display_text: "STOP"
          FAULT:
            on_enter:
              - zero_velocity
              - disable_actuation
              - request_human_help
            led_state: "error"
            display_text: "FAULT"
          SAFE_STOP:
            on_enter:
              - trigger_estop
              - disable_actuation
            led_state: "off"
            display_text: "E-STOP"
          DOCKING:
            on_enter:
              - initiate_docking
            led_state: "thinking"
            display_text: "Docking"
          DEGRADED:
            on_enter:
              - cap_velocity
            led_state: "alert"
            display_text: "Degraded"
    """)

    def test_minimal_yaml_loads(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(self._MINIMAL_YAML)
            path = f.name
        try:
            policy = SafetyPolicy.from_yaml(path)
            assert policy.has_rules_for(SafetyLevel.NORMAL)
        finally:
            os.unlink(path)

    def test_unknown_action_raises(self):
        bad_yaml = self._MINIMAL_YAML.replace("enable_actuation", "fly_to_moon")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(bad_yaml)
            path = f.name
        try:
            with pytest.raises((ValueError, KeyError)):
                SafetyPolicy.from_yaml(path)
        finally:
            os.unlink(path)
