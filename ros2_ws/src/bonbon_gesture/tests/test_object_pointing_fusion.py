"""Tests for PointingObjectFusion -- pointing_at_object geometry."""

from __future__ import annotations

import unittest

from bonbon_gesture.logic.object_pointing_fusion import (
    PointableObject,
    PointingObjectFusion,
)


def _obj(track_id: str, class_name: str, cx: float, cy: float, w: float = 40, h: float = 40):
    """Build a PointableObject with a given bbox center."""
    return PointableObject(
        track_id=track_id,
        class_name=class_name,
        bbox_x=cx - w / 2,
        bbox_y=cy - h / 2,
        bbox_w=w,
        bbox_h=h,
    )


class TestPointingObjectFusion(unittest.TestCase):
    """Tests for find_pointed_object."""

    def setUp(self) -> None:
        self.fusion = PointingObjectFusion(angle_tolerance_deg=25.0)

    def test_object_directly_in_pointing_line_is_found(self) -> None:
        """An object straight ahead of the pointing direction is matched."""
        wrist = (100.0, 200.0)
        direction = (1.0, 0.0)  # pointing straight right (+x)
        chair = _obj("obj_1", "chair", cx=300.0, cy=200.0)

        result = self.fusion.find_pointed_object(wrist, direction, [chair])
        self.assertIsNotNone(result)
        self.assertEqual(result.track_id, "obj_1")

    def test_object_outside_angle_tolerance_is_not_found(self) -> None:
        """An object far off to the side (90 degrees) is not matched."""
        wrist = (100.0, 200.0)
        direction = (1.0, 0.0)  # pointing right
        chair = _obj("obj_1", "chair", cx=100.0, cy=50.0)  # straight up -- 90 deg off

        result = self.fusion.find_pointed_object(wrist, direction, [chair])
        self.assertIsNone(result)

    def test_object_behind_wrist_is_not_found(self) -> None:
        """An object behind the wrist (opposite the pointing direction) is
        never matched, even if angularly aligned."""
        wrist = (100.0, 200.0)
        direction = (1.0, 0.0)  # pointing right
        chair = _obj("obj_1", "chair", cx=-100.0, cy=200.0)  # directly behind, to the left

        result = self.fusion.find_pointed_object(wrist, direction, [chair])
        self.assertIsNone(result)

    def test_no_objects_returns_none(self) -> None:
        """No candidate objects -- honest None, not a guess."""
        result = self.fusion.find_pointed_object((0.0, 0.0), (1.0, 0.0), [])
        self.assertIsNone(result)

    def test_zero_length_direction_returns_none(self) -> None:
        """A degenerate (zero-length) direction vector cannot be fused."""
        chair = _obj("obj_1", "chair", cx=300.0, cy=200.0)
        result = self.fusion.find_pointed_object((100.0, 200.0), (0.0, 0.0), [chair])
        self.assertIsNone(result)

    def test_closest_angle_object_wins_among_multiple(self) -> None:
        """When two objects both qualify, the smaller-angle one is chosen."""
        wrist = (100.0, 200.0)
        direction = (1.0, 0.0)
        far_off_angle = _obj("obj_far", "table", cx=300.0, cy=280.0)  # some angle off
        near_angle = _obj("obj_near", "chair", cx=300.0, cy=205.0)  # nearly straight ahead

        result = self.fusion.find_pointed_object(wrist, direction, [far_off_angle, near_angle])
        self.assertIsNotNone(result)
        self.assertEqual(result.track_id, "obj_near")

    def test_stricter_tolerance_rejects_a_moderate_offset(self) -> None:
        """A smaller angle_tolerance_deg is stricter."""
        strict_fusion = PointingObjectFusion(angle_tolerance_deg=5.0)
        wrist = (100.0, 200.0)
        direction = (1.0, 0.0)
        chair = _obj("obj_1", "chair", cx=300.0, cy=240.0)  # a moderate angular offset

        result = strict_fusion.find_pointed_object(wrist, direction, [chair])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
