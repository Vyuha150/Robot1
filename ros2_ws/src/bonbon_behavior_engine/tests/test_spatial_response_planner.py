"""Unit tests for bonbon_behavior_engine.core.spatial_response_planner."""

from __future__ import annotations

from bonbon_behavior_engine.core.spatial_response_planner import SpatialResponsePlanner


class TestHintResponses:
    def setup_method(self):
        self.p = SpatialResponsePlanner()

    def test_stop_pauses_navigation(self):
        r = self.p.plan_for_hint("stop")
        assert r.pause_navigation is True
        assert r.gesture == "stop_gesture"

    def test_slow_down_is_passive(self):
        r = self.p.plan_for_hint("slow_down")
        assert r.pause_navigation is False
        assert r.gesture == ""
        assert r.escalate_to_operator is False

    def test_retreat_gesture(self):
        r = self.p.plan_for_hint("retreat")
        assert r.pause_navigation is True
        assert r.gesture == "slight_retreat"
        assert r.say

    def test_announce_speaks(self):
        r = self.p.plan_for_hint("announce")
        assert r.say
        assert r.tts_emotion == "friendly"

    def test_unknown_hint_is_neutral(self):
        r = self.p.plan_for_hint("nonsense")
        assert r.pause_navigation is False
        assert r.gesture == ""
        assert r.escalate_to_operator is False

    def test_high_urgency_stop_escalates(self):
        r = self.p.plan_for_hint("stop", urgency=0.95)
        assert r.escalate_to_operator is True
        assert r.operator_severity >= 3


class TestAlertResponses:
    def setup_method(self):
        self.p = SpatialResponsePlanner()

    def test_restricted_zone_escalates(self):
        r = self.p.plan_for_alert("restricted_zone_entry", severity=3)
        assert r.escalate_to_operator is True
        assert r.say

    def test_path_blocked_pauses_and_speaks(self):
        r = self.p.plan_for_alert("path_blocked", severity=2)
        assert r.pause_navigation is True
        assert r.say
        assert r.escalate_to_operator is False

    def test_collision_risk_stop_gesture(self):
        r = self.p.plan_for_alert("collision_risk", severity=3)
        assert r.pause_navigation is True
        assert r.gesture == "stop_gesture"
        assert r.tts_emotion == "urgent"

    def test_critical_severity_always_escalates(self):
        # path_blocked normally does not escalate, but CRITICAL forces it.
        r = self.p.plan_for_alert("path_blocked", severity=4)
        assert r.escalate_to_operator is True
        assert r.operator_severity >= 4

    def test_unknown_alert_neutral(self):
        r = self.p.plan_for_alert("mystery", severity=2)
        assert r.gesture == ""
        assert r.escalate_to_operator is False
