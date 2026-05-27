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
        on_enter=[PolicyAction.disable_actuation, PolicyAction.update_led_eyes],
        led_state="thinking",
        display_text="⚙ Starting up…",
    ),
    "NORMAL": PolicyRule(
        state_name="NORMAL",
        on_enter=[PolicyAction.enable_actuation, PolicyAction.update_led_eyes],
        led_state="happy",
        display_text="",
    ),
    "CAUTION": PolicyRule(
        state_name="CAUTION",
        on_enter=[
            PolicyAction.cap_velocity,
            PolicyAction.announce_audio,
            PolicyAction.update_led_eyes,
            PolicyAction.update_display,
            PolicyAction.notify_operator,
        ],
        on_exit=[PolicyAction.update_led_eyes],
        audio_file="caution_slow_down.wav",
        led_state="alert",
        display_text="⚠ Slowing down",
        announce_text="Slowing down — someone nearby.",
    ),
    "DANGER": PolicyRule(
        state_name="DANGER",
        on_enter=[
            PolicyAction.zero_velocity,
            PolicyAction.cancel_navigation,
            PolicyAction.disable_actuation,
            PolicyAction.announce_audio,
            PolicyAction.update_led_eyes,
            PolicyAction.update_display,
            PolicyAction.log_incident,
            PolicyAction.notify_operator,
        ],
        on_exit=[PolicyAction.enable_actuation],
        audio_file="danger_stop.wav",
        led_state="warning",
        display_text="⛔ STOP",
        announce_text="Please step back.",
    ),
    "FAULT": PolicyRule(
        state_name="FAULT",
        on_enter=[
            PolicyAction.zero_velocity,
            PolicyAction.cancel_navigation,
            PolicyAction.disable_actuation,
            PolicyAction.announce_audio,
            PolicyAction.update_led_eyes,
            PolicyAction.update_display,
            PolicyAction.log_incident,
            PolicyAction.notify_operator,
            PolicyAction.request_human_help,
        ],
        audio_file="fault_alert.wav",
        led_state="error",
        display_text="🔴 FAULT — Operator required",
        announce_text="I have a problem. Please call for assistance.",
    ),
    "SAFE_STOP": PolicyRule(
        state_name="SAFE_STOP",
        on_enter=[
            PolicyAction.trigger_estop,
            PolicyAction.update_led_eyes,
            PolicyAction.update_display,
            PolicyAction.log_incident,
            PolicyAction.notify_operator,
        ],
        led_state="off",
        display_text="🔴 EMERGENCY STOP",
    ),
    "DOCKING": PolicyRule(
        state_name="DOCKING",
        on_enter=[
            PolicyAction.cancel_navigation,
            PolicyAction.initiate_docking,
            PolicyAction.announce_audio,
            PolicyAction.update_led_eyes,
            PolicyAction.update_display,
            PolicyAction.notify_operator,
        ],
        on_exit=[PolicyAction.update_led_eyes],
        audio_file="low_battery_docking.wav",
        led_state="thinking",
        display_text="🔋 Battery low — returning to dock",
        announce_text="My battery is low. I am returning to my charging station.",
    ),
    "DEGRADED": PolicyRule(
        state_name="DEGRADED",
        on_enter=[
            PolicyAction.cap_velocity,
            PolicyAction.update_led_eyes,
            PolicyAction.update_display,
            PolicyAction.notify_operator,
            PolicyAction.log_incident,
        ],
        led_state="alert",
        display_text="⚠ Reduced capability",
    ),
}
