"""Edge AI Runtime brief Phase 13 -- config/edge_ai/three_pi_allocation.yaml.
Validates the brief's UI/AI/Nav Pi naming maps onto the real,
already-deployed config/distributed/*.yaml roles (per
docs/THREE_PI_RUNTIME_AUDIT.md) and that every cross-reference this file
declares (rather than duplicates) actually resolves to a real file and
key -- a broken cross-reference here would silently rot into a dangling
pointer no one notices."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_EDGE_AI_DIR = _REPO_ROOT / "config" / "edge_ai"


class TestThreePiAllocationConfig(unittest.TestCase):
    def setUp(self):
        path = _CONFIG_EDGE_AI_DIR / "three_pi_allocation.yaml"
        self.data = yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_three_pi_roles_declared(self):
        self.assertEqual(
            set(self.data["pi_roles"].keys()),
            {"ui_supervisor_pi", "ai_interaction_pi", "navigation_safety_pi"},
        )

    def test_ui_pi_forbidden_list_includes_direct_motor_control(self):
        forbidden = self.data["pi_roles"]["ui_supervisor_pi"]["forbidden"]
        self.assertIn("direct_motor_control", forbidden)

    def test_ai_pi_behavior_output_is_proposal_only(self):
        behavior_output = self.data["pi_roles"]["ai_interaction_pi"]["behavior_output"]
        self.assertIn("/bonbon/behavior/proposal", behavior_output)
        self.assertIn("never a direct motor command", behavior_output)

    def test_ai_pi_model_load_priority_cross_reference_resolves(self):
        source = self.data["ai_pi_model_load_priority_source"]
        rel_path, _, key = source.partition("#")
        target = _REPO_ROOT / rel_path
        self.assertTrue(target.exists(), f"{source!r} points at a missing file")
        target_data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        self.assertIn(key, target_data, f"{source!r} points at a missing key")

    def test_resource_policy_cross_reference_resolves(self):
        source = self.data["resource_policy_source"]
        target = _REPO_ROOT / source
        self.assertTrue(target.exists(), f"resource_policy_source {source!r} points at a missing file")

    def test_each_pi_role_maps_to_a_real_distributed_config_file(self):
        for role_name, role in self.data["pi_roles"].items():
            maps_to = role["maps_to"]
            rel_path = maps_to.split(" ")[0]
            target = _REPO_ROOT / rel_path
            self.assertTrue(target.exists(), f"{role_name}'s maps_to {maps_to!r} points at a missing file")


if __name__ == "__main__":
    unittest.main()
