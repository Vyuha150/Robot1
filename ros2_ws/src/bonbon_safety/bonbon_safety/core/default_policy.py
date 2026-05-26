"""
bonbon_safety.core.default_policy
====================================
Built-in conservative default policy used when no YAML file is provided.
This ensures the robot always has a valid policy even on first boot.
"""

from bonbon_safety.core.safety_policy import PolicyAction, PolicyRule

DEFAULT_POLICY_RULES = {
    "INITIALIZING": PolicyRule(
        state_name="INITIALIZING",
        on_enter=[PolicyAction.DISABLE_ACTUATION, PolicyAction.UPDATE_LED_EYES],
        led_state="thinking",
        display_text="⚙ Starting up…",
    ),
    "NORMAL": PolicyRule(
        state_name="NORMAL",
        on_enter=[PolicyAction.ENABLE_ACTUATION, PolicyAction.UPDATE_LED_EYES],
        led_state="happy",
        display_text="",
    ),
    "CAUTION": PolicyRule(
        state_name="CAUTION",
        on_enter=[
            PolicyAction.CAP_VELOCITY,
            PolicyAction.ANNOUNCE_AUDIO,
            PolicyAction.UPDATE_LED_EYES,
            PolicyAction.UPDATE_DISPLAY,
            PolicyAction.NOTIFY_OPERATOR,
        ],
        on_exit=[PolicyAction.UPDATE_LED_EYES],
        audio_file="caution_slow_down.wav",
        led_state="alert",
        display_text="⚠ Slowing down",
        announce_text="Slowing down — someone nearby.",
    ),
    "DANGER": PolicyRule(
        state_name="DANGER",
        on_enter=[
            PolicyAction.ZERO_VELOCITY,
            PolicyAction.CANCEL_NAVIGATION,
            PolicyAction.DISABLE_ACTUATION,
            PolicyAction.ANNOUNCE_AUDIO,
            PolicyAction.UPDATE_LED_EYES,
            PolicyAction.UPDATE_DISPLAY,
            PolicyAction.LOG_INCIDENT,
            PolicyAction.NOTIFY_OPERATOR,
        ],
        on_exit=[PolicyAction.ENABLE_ACTUATION],
        audio_file="danger_stop.wav",
        led_state="warning",
        display_text="⛔ STOP",
        announce_text="Please step back.",
    ),
    "FAULT": PolicyRule(
        state_name="FAULT",
        on_enter=[
            PolicyAction.ZERO_VELOCITY,
            PolicyAction.CANCEL_NAVIGATION,
            PolicyAction.DISABLE_ACTUATION,
            PolicyAction.ANNOUNCE_AUDIO,
            PolicyAction.UPDATE_LED_EYES,
            PolicyAction.UPDATE_DISPLAY,
            PolicyAction.LOG_INCIDENT,
            PolicyAction.NOTIFY_OPERATOR,
            PolicyAction.REQUEST_HUMAN_HELP,
        ],
        audio_file="fault_alert.wav",
        led_state="error",
        display_text="🔴 FAULT — Operator required",
        announce_text="I have a problem. Please call for assistance.",
    ),
    "SAFE_STOP": PolicyRule(
        state_name="SAFE_STOP",
        on_enter=[
            PolicyAction.TRIGGER_ESTOP,
            PolicyAction.UPDATE_LED_EYES,
            PolicyAction.UPDATE_DISPLAY,
            PolicyAction.LOG_INCIDENT,
            PolicyAction.NOTIFY_OPERATOR,
        ],
        led_state="off",
        display_text="🔴 EMERGENCY STOP",
    ),
    "DOCKING": PolicyRule(
        state_name="DOCKING",
        on_enter=[
            PolicyAction.CANCEL_NAVIGATION,
            PolicyAction.INITIATE_DOCKING,
            PolicyAction.ANNOUNCE_AUDIO,
            PolicyAction.UPDATE_LED_EYES,
            PolicyAction.UPDATE_DISPLAY,
            PolicyAction.NOTIFY_OPERATOR,
        ],
        on_exit=[PolicyAction.UPDATE_LED_EYES],
        audio_file="low_battery_docking.wav",
        led_state="thinking",
        display_text="🔋 Battery low — returning to dock",
        announce_text="My battery is low. I am returning to my charging station.",
    ),
    "DEGRADED": PolicyRule(
        state_name="DEGRADED",
        on_enter=[
            PolicyAction.CAP_VELOCITY,
            PolicyAction.UPDATE_LED_EYES,
            PolicyAction.UPDATE_DISPLAY,
            PolicyAction.NOTIFY_OPERATOR,
            PolicyAction.LOG_INCIDENT,
        ],
        led_state="alert",
        display_text="⚠ Reduced capability",
    ),
}
