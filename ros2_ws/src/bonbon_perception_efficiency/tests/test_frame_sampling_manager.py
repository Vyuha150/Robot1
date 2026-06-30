"""Tests for FrameSamplingManager."""

from __future__ import annotations

from bonbon_perception_efficiency.core.frame_sampling_manager import FrameSamplingManager


class TestNominalLoad:
    def test_full_scale_keeps_base_rate(self):
        mgr = FrameSamplingManager(base_rates={"vision": 1})
        recs = mgr.recommend(load_shed_scale=1.0)
        assert recs[0].sample_every_n_frames == 1
        assert recs[0].reason == "nominal load"


class TestLoadShedding:
    def test_reduced_scale_increases_sample_interval(self):
        mgr = FrameSamplingManager(base_rates={"gesture": 3})
        recs = mgr.recommend(load_shed_scale=0.5)
        assert recs[0].sample_every_n_frames > 3

    def test_never_samples_less_often_than_base(self):
        """Load shedding should never recommend MORE frequent sampling than
        the package's own nominal baseline."""
        mgr = FrameSamplingManager(base_rates={"vision": 2})
        recs = mgr.recommend(load_shed_scale=1.0)
        assert recs[0].sample_every_n_frames >= 2

    def test_scale_clamped_below_minimum(self):
        mgr = FrameSamplingManager(base_rates={"vision": 1})
        recs = mgr.recommend(load_shed_scale=0.0)
        # Must not divide by zero or recommend an absurd/infinite interval.
        assert recs[0].sample_every_n_frames < 100


class TestMultipleConsumers:
    def test_each_consumer_gets_its_own_recommendation(self):
        mgr = FrameSamplingManager(base_rates={"vision": 1, "gesture": 3})
        recs = mgr.recommend(load_shed_scale=1.0)
        consumers = {r.consumer for r in recs}
        assert consumers == {"vision", "gesture"}
