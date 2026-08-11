"""Tests for bonbon_behavior_engine.core.behavior_recommendation_bridge
-- GAP-E2 fix. Pure logic, no rclpy required."""

from __future__ import annotations

from bonbon_behavior_engine.core.behavior_recommendation_bridge import (
    ProposalFields,
    recommendation_to_proposal,
)


class TestRecommendationToProposal:
    def test_navigate_to_goal_converts_with_named_location(self):
        fields = recommendation_to_proposal(
            behavior_class="navigate_to_goal",
            param_names=["named_location", "goal_x", "goal_y", "goal_yaw"],
            param_values=["cardiology", "3.5", "-1.2", "1.57"],
            confidence=0.9,
            priority=1,
        )
        assert isinstance(fields, ProposalFields)
        assert fields.proposal_type == "navigate"
        assert fields.nav_goal_label == "cardiology"
        assert fields.nav_goal_x == 3.5
        assert fields.nav_goal_y == -1.2
        assert fields.safety_check_required is True

    def test_approach_person_converts(self):
        fields = recommendation_to_proposal(
            behavior_class="approach_person",
            param_names=["goal_x", "goal_y", "goal_yaw"],
            param_values=["1.0", "2.0", "0.0"],
            confidence=0.8,
        )
        assert fields.proposal_type == "approach"

    def test_stop_navigation_is_not_bridged(self):
        # stop_navigation is a cancellation handled directly by
        # navigation_node -- the bridge must not produce a proposal for it.
        fields = recommendation_to_proposal(
            behavior_class="stop_navigation", param_names=[], param_values=[], confidence=1.0
        )
        assert fields is None

    def test_unrelated_behavior_class_returns_none(self):
        fields = recommendation_to_proposal(
            behavior_class="serve_item", param_names=[], param_values=[], confidence=0.5
        )
        assert fields is None

    def test_malformed_goal_params_returns_none_not_zero_goal(self):
        # A malformed goal_x must never silently become 0.0 -- that's a
        # real location (the origin), not "no goal given".
        fields = recommendation_to_proposal(
            behavior_class="navigate_to_goal",
            param_names=["goal_x", "goal_y"],
            param_values=["not_a_number", "2.0"],
            confidence=0.9,
        )
        assert fields is None

    def test_urgency_scales_with_priority(self):
        low = recommendation_to_proposal(
            "navigate_to_goal", ["goal_x", "goal_y"], ["1.0", "1.0"], confidence=0.9, priority=0
        )
        urgent = recommendation_to_proposal(
            "navigate_to_goal", ["goal_x", "goal_y"], ["1.0", "1.0"], confidence=0.9, priority=3
        )
        assert low.urgency < urgent.urgency
        assert urgent.urgency == 1.0
