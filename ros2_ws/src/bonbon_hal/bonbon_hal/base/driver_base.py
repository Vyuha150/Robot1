"""
bonbon_hal.base.driver_base
============================
Abstract base class for every BonBon hardware driver.

All hardware access in the system MUST go through a class that inherits
from DriverBase.  No AI module, ROS2 node, or user code may touch raw
hardware (GPIO, I2C, USB, serial) directly.

Design principles
-----------------
- Zero ROS2 dependency: drivers are pure Python, testable without a robot.
- Every driver is a context manager (with-statement safe).
- All faults are expressed as DriverFault exceptions or DriverHealth reports,
  never as bare Python exceptions propagating to callers.
- Subclasses only implement `_do_connect`, `_do_disconnect`, `_do_read*`.
  Reconnection, health tracking, and fault counting are handled here.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


class DriverStatus(IntEnum):
    """Lifecycle status of a hardware driver."""

    DISCONNECTED = 0  # not yet connected or explicitly disconnected
    CONNECTING = 1  # connect() in progress
    CONNECTED = 2  # healthy, data flowing
    DEGRADED = 3  # connected but some reads failing (partial data)
    FAULTED = 4  # hardware error, automatic reconnect in progress
    SHUTDOWN = 5  # permanently closed, do not reconnect


@dataclass
class DriverHealth:
    """
    Snapshot of a driver's runtime health.  Published at 1 Hz to the
    watchdog via the ROS2 node wrapper.
    """

    device: str
    driver_mode: str  # "real" | "mock"
    status: DriverStatus
    is_connected: bool
    last_read_age_sec: float  # seconds since last successful read
    consecutive_errors: int
    total_faults: int
    reconnect_count: int
    last_error: str | None  # last error message
    uptime_sec: float
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def is_healthy(self) -> bool:
        return self.status in (DriverStatus.CONNECTED, DriverStatus.DEGRADED)


class DriverFault(Exception):
    """Raised by drivers on unrecoverable or unexpected hardware errors."""

    def __init__(self, message: str, error_code: str = "UNKNOWN", recoverable: bool = True):
        super().__init__(message)
        self.error_code = error_code
        self.recoverable = recoverable


class DriverBase(ABC):
    """
    Abstract base for all BonBon hardware drivers.

    Parameters
    ----------
    device_name:
        Human-readable device identifier ("camera", "lidar", etc.)
    driver_mode:
        "real" for hardware, "mock" for simulation.
    connect_timeout_sec:
        How long to wait during connect() before raising DriverFault.
    read_timeout_sec:
        How long a read operation may block before timing out.
    """

    def __init__(
        self,
        device_name: str,
        driver_mode: str = "real",
        connect_timeout_sec: float = 5.0,
        read_timeout_sec: float = 1.0,
    ) -> None:
        self._device = device_name
        self._mode = driver_mode
        self._connect_timeout = connect_timeout_sec
        self._read_timeout = read_timeout_sec

        self._status: DriverStatus = DriverStatus.DISCONNECTED
        self._lock = threading.Lock()
        self._consecutive_errors: int = 0
        self._total_faults: int = 0
        self._reconnect_count: int = 0
        self._last_error: str | None = None
        self._last_read_ts: float = 0.0
        self._connect_ts: float = 0.0
        self._start_ts: float = time.monotonic()

        # Optional fault callback: called with (device_name, error_code, message)
        self._fault_cb = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """
        Open the hardware connection.  Returns True on success.
        Sets status to CONNECTED on success, FAULTED on failure.
        """
        with self._lock:
            if self._status == DriverStatus.SHUTDOWN:
                raise DriverFault("Driver is shut down", "SHUTDOWN", recoverable=False)
            self._status = DriverStatus.CONNECTING

        logger.info("[%s/%s] Connecting…", self._device, self._mode)
        try:
            ok = self._do_connect()
            if ok:
                with self._lock:
                    self._status = DriverStatus.CONNECTED
                    self._consecutive_errors = 0
                    self._connect_ts = time.monotonic()
                logger.info("[%s/%s] Connected", self._device, self._mode)
                return True
            else:
                self._record_fault("CONNECT_FAILED", "connect returned False")
                return False
        except Exception as exc:
            self._record_fault("CONNECT_EXCEPTION", str(exc))
            return False

    def disconnect(self) -> None:
        """Close the hardware connection gracefully."""
        logger.info("[%s/%s] Disconnecting", self._device, self._mode)
        try:
            self._do_disconnect()
        except Exception as exc:
            logger.warning("[%s/%s] Exception during disconnect: %s", self._device, self._mode, exc)
        with self._lock:
            self._status = DriverStatus.DISCONNECTED

    def shutdown(self) -> None:
        """Permanently close — no reconnects will be attempted after this."""
        self.disconnect()
        with self._lock:
            self._status = DriverStatus.SHUTDOWN
        logger.info("[%s/%s] Shutdown", self._device, self._mode)

    def reconnect(self) -> bool:
        """Disconnect then connect.  Increments reconnect_count on success."""
        logger.warning(
            "[%s/%s] Reconnecting (attempt %d)…",
            self._device,
            self._mode,
            self._reconnect_count + 1,
        )
        self.disconnect()
        ok = self.connect()
        if ok:
            with self._lock:
                self._reconnect_count += 1
        return ok

    def register_fault_callback(self, cb) -> None:
        """Register a callable(device, error_code, message) fired on every fault."""
        self._fault_cb = cb

    @property
    def is_connected(self) -> bool:
        return self._status == DriverStatus.CONNECTED

    @property
    def status(self) -> DriverStatus:
        return self._status

    @property
    def health(self) -> DriverHealth:
        now = time.monotonic()
        return DriverHealth(
            device=self._device,
            driver_mode=self._mode,
            status=self._status,
            is_connected=self.is_connected,
            last_read_age_sec=now - self._last_read_ts if self._last_read_ts else -1.0,
            consecutive_errors=self._consecutive_errors,
            total_faults=self._total_faults,
            reconnect_count=self._reconnect_count,
            last_error=self._last_error,
            uptime_sec=now - self._connect_ts if self._connect_ts else 0.0,
        )

    # ── Context manager ────────────────────────────────────────────────────────

    def __enter__(self) -> DriverBase:
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.shutdown()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _record_success(self) -> None:
        """Call after every successful read."""
        with self._lock:
            self._last_read_ts = time.monotonic()
            self._consecutive_errors = 0
            if self._status == DriverStatus.DEGRADED:
                self._status = DriverStatus.CONNECTED

    def _record_fault(self, error_code: str, message: str) -> None:
        """Call after every failed read or connect."""
        with self._lock:
            self._consecutive_errors += 1
            self._total_faults += 1
            self._last_error = f"[{error_code}] {message}"
            self._status = DriverStatus.FAULTED
        logger.error("[%s/%s] FAULT %s: %s", self._device, self._mode, error_code, message)
        if self._fault_cb:
            try:
                self._fault_cb(self._device, error_code, message)
            except Exception as exc:
                logger.warning("Fault callback raised: %s", exc)

    def _mark_degraded(self, reason: str) -> None:
        with self._lock:
            self._status = DriverStatus.DEGRADED
        logger.warning("[%s/%s] DEGRADED: %s", self._device, self._mode, reason)

    # ── Abstract methods (must implement in subclass) ──────────────────────────

    @abstractmethod
    def _do_connect(self) -> bool:
        """Open hardware connection.  Return True on success."""

    @abstractmethod
    def _do_disconnect(self) -> None:
        """Close hardware connection cleanly."""
