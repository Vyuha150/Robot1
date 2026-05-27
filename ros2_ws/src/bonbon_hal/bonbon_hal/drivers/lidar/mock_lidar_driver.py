"""
Mock LIDAR driver — generates realistic 360° RPLIDAR S2-style scans.

Fault injection parameters
--------------------------
obstacle_at_angle_deg  : insert a wall segment at this angle (deg), -1 = none
obstacle_distance_m    : distance to the obstacle wall
disconnect_after_n     : simulate USB pull after N scans
partial_ring_from_deg  : zero out rays in [partial_ring_from_deg, partial_ring_to_deg]
simulate_latency_sec   : artificial sleep per scan
"""

from __future__ import annotations

import math
import random
import time

from bonbon_hal.base.driver_base import DriverFault

from .lidar_driver import LidarDriver, LidarScan


class MockLidarDriver(LidarDriver):

    RAYS = 360  # RPLIDAR S2 ≈ 7200 samples/rev but we model 1°/ray for simplicity

    def __init__(
        self,
        room_radius_m: float = 3.0,
        obstacle_at_angle_deg: float = -1,
        obstacle_distance_m: float = 1.0,
        obstacle_width_deg: float = 10.0,
        disconnect_after_n: int = 0,
        partial_ring_from_deg: float = -1,
        partial_ring_to_deg: float = -1,
        simulate_latency_sec: float = 0.0,
        start_disconnected: bool = False,
        noise_sigma_m: float = 0.01,
    ) -> None:
        super().__init__(driver_mode="mock")
        self._room_r = room_radius_m
        self._obs_angle = obstacle_at_angle_deg
        self._obs_dist = obstacle_distance_m
        self._obs_width = obstacle_width_deg
        self._disc_after = disconnect_after_n
        self._pr_from = partial_ring_from_deg
        self._pr_to = partial_ring_to_deg
        self._latency = simulate_latency_sec
        self._noise_sigma = noise_sigma_m
        self._scan_count = 0
        self._start_disc = start_disconnected

    def _do_connect(self) -> bool:
        if self._start_disc:
            return False
        time.sleep(0.05)
        return True

    def _do_disconnect(self) -> None:
        pass

    def read_scan(self) -> LidarScan:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if self._latency:
            time.sleep(self._latency)

        self._scan_count += 1
        if self._disc_after > 0 and self._scan_count > self._disc_after:
            self._record_fault("USB_DISCONNECTED", "Simulated USB disconnect")
            raise DriverFault("USB disconnect", "USB_DISCONNECTED")

        ranges = []
        intensities = []
        time.monotonic()

        for i in range(self.RAYS):
            angle_deg = -180.0 + i * (360.0 / self.RAYS)
            r = self._room_r + random.gauss(0, self._noise_sigma)

            # Insert obstacle
            if self._obs_angle >= 0:
                diff = abs(angle_deg - self._obs_angle)
                if diff > 180:
                    diff = 360 - diff
                if diff < self._obs_width / 2:
                    r = min(r, self._obs_dist + random.gauss(0, self._noise_sigma))

            # Partial ring dropout (stale sector)
            if self._pr_from >= 0 and self._pr_to > self._pr_from:
                a = (angle_deg + 360) % 360
                f = self._pr_from % 360
                t_ = self._pr_to % 360
                if f <= a <= t_:
                    r = math.inf

            r = max(0.15, r) if math.isfinite(r) else math.inf
            ranges.append(r)
            intensities.append(200.0 + random.gauss(0, 5))

        self._record_success()
        return LidarScan(
            ranges=ranges,
            intensities=intensities,
            angle_min_rad=-math.pi,
            angle_max_rad=math.pi,
            scan_time_sec=0.1,
        )

    def inject_fault(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
