"""Safety gate and command validator unit tests."""

from __future__ import annotations

import pytest

from bonbon_operator_api.safety.command_validator import CommandValidator, ValidationError
from bonbon_operator_api.safety.safety_gate import SafetyCommandGate, SafetyGateError


# ---------------------------------------------------------------------------
# CommandValidator tests
# ---------------------------------------------------------------------------

@pytest.fixture
def cv():
    return CommandValidator(dedup_window_sec=5.0, dedup_capacity=64)


# Scenario 1: Valid speak command
def test_validate_speak_valid(cv):
    from bonbon_operator_api.models.command_models import SpeakCommand
    cmd = SpeakCommand(text="Hello!")
    cv.validate_speak(cmd)  # no exception


# Scenario 2: Empty speak text rejected
def test_validate_speak_empty(cv):
    from bonbon_operator_api.models.command_models import SpeakCommand
    cmd = SpeakCommand(text="   ")
    with pytest.raises(ValidationError):
        cv.validate_speak(cmd)


# Scenario 3: Speak text with blocked pattern
def test_validate_speak_blocked_pattern(cv):
    from bonbon_operator_api.models.command_models import SpeakCommand
    cmd = SpeakCommand(text="Enter your password below")
    with pytest.raises(ValidationError) as exc_info:
        cv.validate_speak(cmd)
    assert exc_info.value.code == "BLOCKED_CONTENT"


# Scenario 4: Token in speak text blocked
def test_validate_speak_token_blocked(cv):
    from bonbon_operator_api.models.command_models import SpeakCommand
    cmd = SpeakCommand(text="My api_key is 12345")
    with pytest.raises(ValidationError):
        cv.validate_speak(cmd)


# Scenario 5: Valid navigate command
def test_validate_navigate_valid(cv):
    from bonbon_operator_api.models.command_models import NavigateCommand
    cmd = NavigateCommand(goal_x=10.0, goal_y=-5.0, speed_limit_mps=0.5)
    cv.validate_navigate(cmd)  # no exception


# Scenario 6: Navigate out of bounds (use 250.0 — passes pydantic ±1000 but fails CV ±200)
def test_validate_navigate_out_of_bounds(cv):
    from bonbon_operator_api.models.command_models import NavigateCommand
    cmd = NavigateCommand(goal_x=250.0, goal_y=0.0)
    with pytest.raises(ValidationError) as exc_info:
        cv.validate_navigate(cmd)
    assert exc_info.value.code == "NAV_OUT_OF_BOUNDS"


# Scenario 7: Navigate speed too high (bypass pydantic via model_construct for unit test)
def test_validate_navigate_speed_too_high(cv):
    from bonbon_operator_api.models.command_models import NavigateCommand
    cmd = NavigateCommand.model_construct(goal_x=1.0, goal_y=1.0, speed_limit_mps=5.0)
    with pytest.raises(ValidationError) as exc_info:
        cv.validate_navigate(cmd)
    assert exc_info.value.code == "NAV_SPEED_INVALID"


# Scenario 8: Navigate speed too low (bypass pydantic via model_construct for unit test)
def test_validate_navigate_speed_too_low(cv):
    from bonbon_operator_api.models.command_models import NavigateCommand
    cmd = NavigateCommand.model_construct(goal_x=1.0, goal_y=1.0, speed_limit_mps=0.01)
    with pytest.raises(ValidationError):
        cv.validate_navigate(cmd)


# Scenario 9: Emergency stop with reason
def test_validate_emergency_stop_valid(cv):
    from bonbon_operator_api.models.command_models import EmergencyStopCommand
    cmd = EmergencyStopCommand(reason="Obstacle detected")
    cv.validate_emergency_stop(cmd)  # no exception


# Scenario 10: Emergency stop empty reason
def test_validate_emergency_stop_empty_reason(cv):
    from bonbon_operator_api.models.command_models import EmergencyStopCommand
    cmd = EmergencyStopCommand(reason="  ")
    with pytest.raises(ValidationError):
        cv.validate_emergency_stop(cmd)


# Scenario 11: Dedup — first call returns False
def test_dedup_first_call_false(cv):
    assert cv.check_duplicate("cmd-abc") is False


# Scenario 12: Dedup — second call returns True
def test_dedup_second_call_true(cv):
    cv.check_duplicate("cmd-dup")
    assert cv.check_duplicate("cmd-dup") is True


# Scenario 13: Dedup window expiry — simulate by back-dating the entry timestamp
def test_dedup_expiry():
    import time
    cv2 = CommandValidator(dedup_window_sec=1.0, dedup_capacity=64)
    # Register a command with a timestamp 2 seconds in the past
    old_ts = time.monotonic() - 2.0
    cv2._recent.append(("cmd-expiry", old_ts))
    # Now check_duplicate should expire the old entry and accept it as new
    result = cv2.check_duplicate("cmd-expiry")
    assert result is False  # expired and re-accepted


# ---------------------------------------------------------------------------
# SafetyCommandGate tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_aggregator_normal():
    from unittest.mock import MagicMock
    agg = MagicMock()
    status = MagicMock()
    status.safety.state = "normal"
    agg.get_status.return_value = status
    return agg


@pytest.fixture
def mock_aggregator_estop():
    from unittest.mock import MagicMock
    agg = MagicMock()
    status = MagicMock()
    status.safety.state = "emergency_stop"
    agg.get_status.return_value = status
    return agg


@pytest.fixture
def gate_normal(mock_aggregator_normal, audit_logger):
    cv = CommandValidator()
    return SafetyCommandGate(cv, mock_aggregator_normal, audit_logger)


@pytest.fixture
def gate_estop(mock_aggregator_estop, audit_logger):
    cv = CommandValidator()
    return SafetyCommandGate(cv, mock_aggregator_estop, audit_logger)


# Scenario 14: Normal state allows navigate
def test_gate_navigate_allowed_normal(gate_normal):
    from bonbon_operator_api.models.command_models import NavigateCommand
    cmd = NavigateCommand(goal_x=1.0, goal_y=1.0)
    gate_normal.check_and_validate(
        "navigate", cmd, "cmd-001", "uid1", "alice", "operator"
    )  # no exception


# Scenario 15: Emergency stop state blocks navigate
def test_gate_navigate_blocked_estop(gate_estop):
    from bonbon_operator_api.models.command_models import NavigateCommand
    cmd = NavigateCommand(goal_x=1.0, goal_y=1.0)
    with pytest.raises(SafetyGateError) as exc_info:
        gate_estop.check_and_validate(
            "navigate", cmd, "cmd-002", "uid1", "alice", "operator"
        )
    assert exc_info.value.code == "SAFETY_STATE_BLOCKED"


# Scenario 16: Emergency stop command always passes in estop state
def test_gate_emergency_stop_always_passes(gate_estop):
    from bonbon_operator_api.models.command_models import EmergencyStopCommand
    cmd = EmergencyStopCommand(reason="Halt!")
    gate_estop.check_and_validate(
        "emergency_stop", cmd, "cmd-003", "uid1", "alice", "operator"
    )  # no exception


# Scenario 17: Gate records audit entry on accept
def test_gate_records_audit_on_accept(gate_normal, audit_logger):
    from bonbon_operator_api.models.command_models import SpeakCommand
    before = audit_logger.count()
    cmd = SpeakCommand(text="Hi there!")
    gate_normal.check_and_validate(
        "speak", cmd, "cmd-audit-1", "uid1", "alice", "operator"
    )
    assert audit_logger.count() > before


# Scenario 18: Gate records audit entry on block
def test_gate_records_audit_on_block(gate_estop, audit_logger):
    from bonbon_operator_api.models.command_models import NavigateCommand
    before = audit_logger.count()
    cmd = NavigateCommand(goal_x=1.0, goal_y=1.0)
    with pytest.raises(SafetyGateError):
        gate_estop.check_and_validate(
            "navigate", cmd, "cmd-audit-2", "uid1", "alice", "operator"
        )
    assert audit_logger.count() > before


# Scenario 19: speak not in _BLOCKED_DURING_HALT — passes even in estop
def test_gate_speak_allowed_during_estop(gate_estop):
    from bonbon_operator_api.models.command_models import SpeakCommand
    cmd = SpeakCommand(text="Safe message")
    gate_estop.check_and_validate(
        "speak", cmd, "cmd-speak-estop", "uid1", "alice", "operator"
    )  # no exception


# Scenario 20: Duplicate command raises DUPLICATE_COMMAND
def test_gate_duplicate_rejected(gate_normal):
    from bonbon_operator_api.models.command_models import SpeakCommand
    cmd = SpeakCommand(text="Hello")
    gate_normal.check_and_validate(
        "speak", cmd, "dup-cmd-99", "uid1", "alice", "operator"
    )
    with pytest.raises(SafetyGateError) as exc_info:
        gate_normal.check_and_validate(
            "speak", cmd, "dup-cmd-99", "uid1", "alice", "operator"
        )
    assert exc_info.value.code == "DUPLICATE_COMMAND"
