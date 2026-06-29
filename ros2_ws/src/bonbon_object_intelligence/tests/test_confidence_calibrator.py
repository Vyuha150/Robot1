"""Tests for ObjectConfidenceCalibrator — class adjustment, small-object floor,
rejection, and near-duplicate collapsing.
"""

from __future__ import annotations

from bonbon_object_intelligence.core.confidence_calibrator import (
    CalibratorConfig,
    ObjectConfidenceCalibrator,
)


class TestClassAdjustment:
    def test_no_adjustment_by_default(self):
        calib = ObjectConfidenceCalibrator()
        result = calib.calibrate("chair", 0.8, (0, 0, 100, 100))
        assert abs(result.calibrated_confidence - 0.8) < 1e-6

    def test_configured_class_adjustment_applied(self):
        cfg = CalibratorConfig(class_confidence_adjustment={"chair": 0.5})
        calib = ObjectConfidenceCalibrator(cfg)
        result = calib.calibrate("chair", 0.8, (0, 0, 100, 100))
        assert abs(result.calibrated_confidence - 0.4) < 1e-6

    def test_adjustment_clamped_to_one(self):
        cfg = CalibratorConfig(class_confidence_adjustment={"chair": 2.0})
        calib = ObjectConfidenceCalibrator(cfg)
        result = calib.calibrate("chair", 0.8, (0, 0, 100, 100))
        assert result.calibrated_confidence <= 1.0


class TestSmallObjectFloor:
    def test_small_object_below_floor_gets_boosted(self):
        cfg = CalibratorConfig(small_object_area_px=900.0, small_object_confidence_floor=0.4)
        calib = ObjectConfidenceCalibrator(cfg)
        result = calib.calibrate("key", 0.2, (0, 0, 10, 10))  # area=100, small
        assert result.is_small_object is True
        assert result.calibrated_confidence == 0.4

    def test_large_object_never_gets_small_object_floor(self):
        cfg = CalibratorConfig(small_object_area_px=900.0, small_object_confidence_floor=0.4)
        calib = ObjectConfidenceCalibrator(cfg)
        result = calib.calibrate("chair", 0.2, (0, 0, 100, 100))  # area=10000, not small
        assert result.is_small_object is False
        assert result.calibrated_confidence == 0.2

    def test_small_object_already_above_floor_unaffected(self):
        cfg = CalibratorConfig(small_object_area_px=900.0, small_object_confidence_floor=0.4)
        calib = ObjectConfidenceCalibrator(cfg)
        result = calib.calibrate("key", 0.9, (0, 0, 10, 10))
        assert result.calibrated_confidence == 0.9


class TestRejection:
    def test_below_threshold_rejected(self):
        cfg = CalibratorConfig(rejection_threshold=0.3)
        calib = ObjectConfidenceCalibrator(cfg)
        result = calib.calibrate("chair", 0.1, (0, 0, 100, 100))
        assert result.rejected is True

    def test_above_threshold_not_rejected(self):
        cfg = CalibratorConfig(rejection_threshold=0.3)
        calib = ObjectConfidenceCalibrator(cfg)
        result = calib.calibrate("chair", 0.5, (0, 0, 100, 100))
        assert result.rejected is False


class TestDuplicateCollapsing:
    def test_overlapping_same_class_collapsed_to_highest_confidence(self):
        calib = ObjectConfidenceCalibrator(CalibratorConfig(duplicate_iou_threshold=0.5))
        dets = [
            ("chair", 0.6, (0, 0, 100, 100)),
            ("chair", 0.9, (5, 5, 100, 100)),  # heavily overlapping, higher conf
        ]
        result = calib.deduplicate(dets)
        assert len(result) == 1
        assert result[0][1] == 0.9

    def test_different_classes_never_collapsed(self):
        calib = ObjectConfidenceCalibrator()
        dets = [("chair", 0.8, (0, 0, 100, 100)), ("bag", 0.7, (0, 0, 100, 100))]
        result = calib.deduplicate(dets)
        assert len(result) == 2

    def test_non_overlapping_same_class_both_kept(self):
        calib = ObjectConfidenceCalibrator(CalibratorConfig(duplicate_iou_threshold=0.5))
        dets = [("chair", 0.8, (0, 0, 50, 50)), ("chair", 0.7, (500, 500, 50, 50))]
        result = calib.deduplicate(dets)
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        calib = ObjectConfidenceCalibrator()
        assert calib.deduplicate([]) == []
