"""
bonbon_safety.core.safety_policy
==================================
Declarative safety policy engine.

Loads rules from safety_policy.yaml.  Each rule maps a SafetyLevel to a set
of prescribed actions.  The supervisor node reads the policy and executes the
appropriate actions when a state transition occurs.

This separates *what* should happen (policy) from *how* it happens (supervisor
node) so the policy can be changed at the deployment site without touching code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class PolicyAction(str, Enum):
    """All possible actions the supervisor can take on a state transition."""
    # Locomotion
    ZERO_VELOCITY          = "zero_velocity"          # publish zero cmd_vel
    CAP_VELOCITY           = "cap_velocity"            # cap cmd_vel at limit
    CANCEL_NAVIGATION      = "cancel_navigation"       # cancel active nav2 goal
    # Actuation
    DISABLE_ACTUATION      = "disable_actuation"       # block servo commands
    ENABLE_ACTUATION       = "enable_actuation"
    # Docking
    INITIATE_DOCKING       = "initiate_docking"        # send dock action goal
    # Audio / UI
    ANNOUNCE_AUDIO         = "announce_audio"          # play named audio file
    UPDATE_LED_EYES        = "update_led_eyes"         # change eye expression
    UPDATE_DISPLAY         = "update_display"          # show message on screen
    # Operator
    NOTIFY_OPERATOR        = "notify_operator"         # push alert to dashboard
    REQUEST_HUMAN_HELP     = "request_human_help"      # announce + dashboard flag
    # Hardware
    TRIGGER_ESTOP          = "trigger_estop"           # assert GPIO e-stop relay
    RELEASE_ESTOP          = "release_estop"
    # Logging
    LOG_INCIDENT           = "log_incident"            # write to safety incident log
    # Node management
    RESTART_FAILED_NODE    = "restart_failed_node"
    ENTER_DEGRADED_MODE    = "enter_degraded_mode"


@dataclass
class PolicyRule:
    """
    A single policy rule for a target safety state.

    on_enter: actions executed once when entering the state.
    on_exit:  actions executed once when leaving the state.
    recurring: actions executed every cycle while in the state.
    audio_file: path (relative to assets/audio/) for ANNOUNCE_AUDIO.
    led_state:  eye expression name for UPDATE_LED_EYES.
    display_text: message for UPDATE_DISPLAY.
    """
    state_name: str
    on_enter: List[PolicyAction] = field(default_factory=list)
    on_exit: List[PolicyAction] = field(default_factory=list)
    recurring: List[PolicyAction] = field(default_factory=list)
    audio_file: Optional[str] = None
    led_state: Optional[str] = None
    display_text: Optional[str] = None
    announce_text: Optional[str] = None


class SafetyPolicy:
    """
    Immutable policy loaded from a YAML file.

    Expected YAML structure
    -----------------------
    rules:
      NORMAL:
        on_enter: [enable_actuation]
        led_state: "happy"
      CAUTION:
        on_enter: [cap_velocity, announce_audio, update_led_eyes, notify_operator]
        audio_file: "caution_human_nearby.wav"
        led_state: "alert"
        announce_text: "Slowing down — someone nearby."
      DANGER:
        on_enter: [zero_velocity, disable_actuation, announce_audio,
                   update_led_eyes, log_incident, notify_operator]
        audio_file: "danger_stop.wav"
        led_state: "warning"
        display_text: "⚠ STOP"
        announce_text: "Please step back."
      FAULT:
        on_enter: [zero_velocity, disable_actuation, log_incident,
                   notify_operator, request_human_help]
        led_state: "error"
        display_text: "🔴 FAULT — Contact operator"
      SAFE_STOP:
        on_enter: [trigger_estop, log_incident, notify_operator]
        led_state: "off"
      DOCKING:
        on_enter: [announce_audio, update_led_eyes, update_display]
        audio_file: "low_battery_docking.wav"
        led_state: "thinking"
        display_text: "🔋 Returning to dock..."
    """

    def __init__(self, rules: Dict[str, PolicyRule]) -> None:
        self._rules = rules

    @classmethod
    def from_yaml(cls, path: Path) -> "SafetyPolicy":
        """Load and validate policy from a YAML file."""
        if not path.exists():
            raise FileNotFoundError(f"Safety policy not found: {path}")

        with path.open() as fh:
            raw = yaml.safe_load(fh)

        if "rules" not in raw:
            raise ValueError("safety_policy.yaml must have a top-level 'rules' key")

        rules: Dict[str, PolicyRule] = {}
        for state_name, rule_dict in raw["rules"].items():
            on_enter = [
                PolicyAction(a) for a in rule_dict.get("on_enter", [])
            ]
            on_exit = [
                PolicyAction(a) for a in rule_dict.get("on_exit", [])
            ]
            recurring = [
                PolicyAction(a) for a in rule_dict.get("recurring", [])
            ]
            rules[state_name] = PolicyRule(
                state_name=state_name,
                on_enter=on_enter,
                on_exit=on_exit,
                recurring=recurring,
                audio_file=rule_dict.get("audio_file"),
                led_state=rule_dict.get("led_state"),
                display_text=rule_dict.get("display_text"),
                announce_text=rule_dict.get("announce_text"),
            )

        logger.info(
            "Safety policy loaded from %s — %d rules", path, len(rules)
        )
        return cls(rules)

    @classmethod
    def default(cls) -> "SafetyPolicy":
        """Factory: returns the built-in conservative default policy."""
        from bonbon_safety.core.default_policy import DEFAULT_POLICY_RULES
        return cls(DEFAULT_POLICY_RULES)

    def rule_for(self, state_name: str) -> Optional[PolicyRule]:
        """Return the rule for the given state name, or None if not defined."""
        return self._rules.get(state_name)

    def on_enter_actions(self, state_name: str) -> List[PolicyAction]:
        rule = self.rule_for(state_name)
        return rule.on_enter if rule else []

    def on_exit_actions(self, state_name: str) -> List[PolicyAction]:
        rule = self.rule_for(state_name)
        return rule.on_exit if rule else []

    def recurring_actions(self, state_name: str) -> List[PolicyAction]:
        rule = self.rule_for(state_name)
        return rule.recurring if rule else []

    def audio_file(self, state_name: str) -> Optional[str]:
        rule = self.rule_for(state_name)
        return rule.audio_file if rule else None

    def led_state(self, state_name: str) -> Optional[str]:
        rule = self.rule_for(state_name)
        return rule.led_state if rule else None

    def display_text(self, state_name: str) -> Optional[str]:
        rule = self.rule_for(state_name)
        return rule.display_text if rule else None

    def announce_text(self, state_name: str) -> Optional[str]:
        rule = self.rule_for(state_name)
        return rule.announce_text if rule else None
