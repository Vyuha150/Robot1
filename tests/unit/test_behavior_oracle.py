"""Unit tests for the Behavior Oracle: the 10 required correctness checks
against scenarios drawn from the real generated catalog."""

from __future__ import annotations

from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle, ObservedOutcome
from bonbon_behavior_validation.behavior_oracle import OracleStatus


def _scenario(family: str, **filters):
    scenarios = load_generated(family)
    for s in scenarios:
        ic = s.input_conditions
        if all(getattr(ic, k, None) == v for k, v in filters.items()):
            return s
    raise AssertionError(f"no {family} scenario matches {filters}")


class TestSafetyHaltScenarios:
    def test_stop_palm_with_halt_passes(self):
        scenario = _scenario("gesture_understanding", gesture="stop_palm")
        observed = ObservedOutcome(
            safety_decision="blocked",
            estop_triggered=True,
            estop_latency_ms=80.0,
            dashboard_updated=True,
            event_logged=True,
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.PASS, verdict.failed_checks

    def test_stop_palm_ignored_fails(self):
        scenario = _scenario("gesture_understanding", gesture="stop_palm")
        observed = ObservedOutcome(
            safety_decision="approved",
            estop_triggered=False,
            dashboard_updated=True,
            event_logged=True,
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL
        assert "safety_supervisor_decision" in {c.name for c in verdict.failed_checks}

    def test_estop_over_budget_fails(self):
        scenario = _scenario("gesture_understanding", gesture="stop_palm")
        observed = ObservedOutcome(
            safety_decision="blocked",
            estop_triggered=True,
            estop_latency_ms=900.0,
            dashboard_updated=True,
            event_logged=True,
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL
        assert "estop_latency" in {c.name for c in verdict.failed_checks}


class TestClarificationScenarios:
    def test_conflicting_gesture_without_clarification_fails(self):
        scenario = _scenario("gesture_understanding", gesture="conflicting_gestures")
        observed = ObservedOutcome(
            asked_clarification=False, dashboard_updated=True, event_logged=True
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL
        assert "clarification_when_needed" in {c.name for c in verdict.failed_checks}

    def test_conflicting_gesture_with_clarification_passes(self):
        scenario = _scenario("gesture_understanding", gesture="conflicting_gestures")
        observed = ObservedOutcome(
            asked_clarification=True, dashboard_updated=True, event_logged=True
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.PASS, verdict.failed_checks


class TestDegradedModeScenarios:
    def test_sensor_loss_requires_degraded_mode(self):
        scenario = _scenario("sensor_failure", sensor="camera_lost")
        observed = ObservedOutcome(
            degraded_mode_entered=False, dashboard_updated=True, event_logged=True
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL
        assert "degraded_mode_entered" in {c.name for c in verdict.failed_checks}

    def test_shedding_a_never_disable_module_fails(self):
        scenario = _scenario("sensor_failure", sensor="camera_lost")
        observed = ObservedOutcome(
            degraded_mode_entered=True,
            never_disable_modules_active=False,
            dashboard_updated=True,
            event_logged=True,
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL


class TestLLMDirectActionScenarios:
    def test_llm_action_without_authorization_fails(self):
        scenario = _scenario("behavior_engine_decisions", gesture="none", speech="clear_speech")
        observed = ObservedOutcome(
            llm_proposed_direct_action=True,
            llm_action_authorized_through_gate=False,
            dashboard_updated=True,
            event_logged=True,
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL
        assert "llm_no_direct_action" in {c.name for c in verdict.failed_checks}

    def test_llm_action_gated_through_authorizer_passes(self):
        scenario = _scenario("behavior_engine_decisions", gesture="none", speech="clear_speech")
        observed = ObservedOutcome(
            llm_proposed_direct_action=True,
            llm_action_authorized_through_gate=True,
            dashboard_updated=True,
            event_logged=True,
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.PASS, verdict.failed_checks


class TestIdentityScenarios:
    def test_identity_mixup_in_multi_person_fails(self):
        scenario = _scenario("multi_person_tracking", people="crowd")
        observed = ObservedOutcome(
            identity_mixup_detected=True, dashboard_updated=True, event_logged=True
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL

    def test_no_mixup_passes(self):
        scenario = _scenario("multi_person_tracking", people="crowd")
        observed = ObservedOutcome(
            identity_mixup_detected=False, dashboard_updated=True, event_logged=True
        )
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.PASS, verdict.failed_checks


class TestDashboardAndLogging:
    def test_missing_dashboard_update_fails(self):
        scenario = _scenario("dashboard_and_operator_control")
        observed = ObservedOutcome(dashboard_updated=False, event_logged=True)
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL
        assert "dashboard_updated" in {c.name for c in verdict.failed_checks}

    def test_missing_event_log_fails(self):
        scenario = _scenario("dashboard_and_operator_control")
        observed = ObservedOutcome(dashboard_updated=True, event_logged=False)
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL
        assert "event_logged" in {c.name for c in verdict.failed_checks}


class TestVerdictSerialization:
    def test_to_dict_round_trips_status_and_checks(self):
        scenario = _scenario("dashboard_and_operator_control")
        observed = ObservedOutcome(dashboard_updated=True, event_logged=True)
        verdict = BehaviorOracle().evaluate(scenario, observed)
        d = verdict.to_dict()
        assert d["scenario_id"] == scenario.scenario_id
        assert d["status"] == "pass"
        assert isinstance(d["checks"], list) and len(d["checks"]) > 0
