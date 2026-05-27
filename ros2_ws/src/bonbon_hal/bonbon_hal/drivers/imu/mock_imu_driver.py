"""
Mock IMU driver — simulates MPU-6050 at configurable rate.

Fault injection:
  spike_every_n_reads    : inject a large gyro spike every N reads
  drift_rate_rad_s       : simulate gyro bias drift
  disconnect_after_n     : simulate I2C disconnect after N reads
  simulate_latency_sec   : artificial sleep
"""

from __future__ import annotations

import math
import random
import time

from bonbon_hal.base.driver_base import DriverFault

from .imu_driver import ImuDriver, ImuReading


class MockImuDriver(ImuDriver):

    def __init__(
        self,
        spike_every_n_reads: int = 0,
        drift_rate_rad_s: float = 0.0,
        disconnect_after_n: int = 0,
        simulate_latency_sec: float = 0.0,
        start_disconnected: bool = False,
        noise_accel: float = 0.02,
        noise_gyro: float = 0.001,
    ) -> None:
        super().__init__(driver_mode="mock")
        self._spike_every = spike_every_n_reads
        self._drift_rate = drift_rate_rad_s
        self._disc_after = disconnect_after_n
        self._latency = simulate_latency_sec
        self._start_disc = start_disconnected
        self._noise_a = noise_accel
        self._noise_g = noise_gyro
        self._read_count = 0
        self._gyro_bias_z = 0.0

    def _do_connect(self) -> bool:
        if self._start_disc:
            return False
        time.sleep(0.02)
        return True

    def _do_disconnect(self) -> None:
        pass

    def calibrate(self) -> None:
        # In mock, calibration is instantaneous
        self._gyro_bias_z = 0.0

    def read(self) -> ImuReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if self._latency:
            time.sleep(self._latency)

        self._read_count += 1
        n = self._read_count

        if self._disc_after > 0 and n > self._disc_after:
            self._record_fault("I2C_DISCONNECT", "Simulated I2C disconnect")
            raise DriverFault("I2C disconnect", "I2C_DISCONNECT")

        # Drift accumulation
        self._gyro_bias_z += self._drift_rate * 0.01  # assume 100 Hz

        t = time.monotonic()
        # Gentle rocking motion simulation
        rock = 0.3 * math.sin(t * 0.5)

        gx = random.gauss(rock * 0.1, self._noise_g)
        gy = random.gauss(0, self._noise_g)
        gz = random.gauss(self._gyro_bias_z, self._noise_g)

        ax = random.gauss(0, self._noise_a)
        ay = random.gauss(0, self._noise_a)
        az = random.gauss(9.81, self._noise_a)

        temp = random.gauss(28.0, 0.5)

        # Inject spike
        if self._spike_every > 0 and n % self._spike_every == 0:
            gx = random.choice([-5.0, 5.0])
            gy = random.choice([-5.0, 5.0])

        self._record_success()
        return ImuReading(
            accel_x=ax,
            accel_y=ay,
            accel_z=az,
            gyro_x=gx,
            gyro_y=gy,
            gyro_z=gz,
            temperature_c=temp,
            accel_covariance=self._noise_a**2,
            gyro_covariance=self._noise_g**2,
        )

    def inject_fault(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
