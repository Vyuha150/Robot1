"""
Dynamixel XL-series servo driver via USB2Dynamixel / U2D2.

SDK dependency: dynamixel_sdk  (pip install dynamixel-sdk)
Hardware:       USB serial, typically /dev/ttyUSB0 or /dev/ttyACM0
Protocol:       Dynamixel Protocol 2.0 (XL430, XM430, XC430, etc.)

Control table addresses (XL430-W250)
--------------------------------------
ADDR_TORQUE_ENABLE     = 64
ADDR_GOAL_POSITION     = 116   (4 bytes, 0–4095 for 360°)
ADDR_GOAL_VELOCITY     = 104   (4 bytes)
ADDR_PROFILE_ACCEL     = 108   (4 bytes)
ADDR_PRESENT_POSITION  = 132
ADDR_PRESENT_VELOCITY  = 128
ADDR_PRESENT_LOAD      = 126
ADDR_PRESENT_TEMP      = 146
ADDR_PRESENT_VOLTAGE   = 144
ADDR_HARDWARE_ERROR    = 70
"""

from __future__ import annotations

import logging
import math

from bonbon_hal.base.driver_base import DriverFault

from .servo_driver import ServoCommand, ServoDriver, ServoReading

logger = logging.getLogger(__name__)

try:
    from dynamixel_sdk import (  # type: ignore[import]
        COMM_SUCCESS,
        DXL_HIBYTE,
        DXL_HIWORD,
        DXL_LOBYTE,
        DXL_LOWORD,
        GroupSyncRead,
        GroupSyncWrite,
        PacketHandler,
        PortHandler,
    )

    _HAS_SDK = True
except ImportError:
    _HAS_SDK = False
    logger.warning("dynamixel_sdk not installed. pip install dynamixel-sdk")

# XL430-W250 control table
_TORQUE_ENABLE = 64
_GOAL_VELOCITY = 104
_PROFILE_ACCEL = 108
_GOAL_POSITION = 116
_PRESENT_LOAD = 126
_PRESENT_VELOCITY = 128
_PRESENT_POSITION = 132
_PRESENT_VOLTAGE = 144
_PRESENT_TEMP = 146
_HARDWARE_ERROR = 70

_PROTOCOL = 2.0
_DXL_MAX_POS = 4095
_DEG_TO_RAD = math.pi / 180.0
_TICK_TO_RAD = 2.0 * math.pi / 4096.0
_VEL_UNIT = 0.229  # rpm per unit
_RPM_TO_RADS = 2.0 * math.pi / 60.0
_LOAD_UNIT = 0.1  # % per unit


class DynamixelDriver(ServoDriver):

    def __init__(
        self,
        servo_ids: list[int],
        port: str = "/dev/ttyUSB0",
        baudrate: int = 57600,
        protocol: float = 2.0,
    ) -> None:
        super().__init__(servo_ids=servo_ids, driver_mode="real")
        self._port = port
        self._baudrate = baudrate
        self._protocol = protocol
        self._port_handler = None
        self._packet_handler = None

    def _do_connect(self) -> bool:
        if not _HAS_SDK:
            raise DriverFault("dynamixel_sdk not installed", "SDK_MISSING", recoverable=False)
        try:
            self._port_handler = PortHandler(self._port)
            self._packet_handler = PacketHandler(self._protocol)

            if not self._port_handler.openPort():
                raise DriverFault(f"Cannot open port {self._port}", "PORT_OPEN_FAILED")
            if not self._port_handler.setBaudRate(self._baudrate):
                raise DriverFault("Cannot set baud rate", "BAUD_FAILED")

            # Ping all registered servos
            for sid in self.servo_ids:
                model, result, error = self._packet_handler.ping(self._port_handler, sid)
                if result != COMM_SUCCESS:
                    logger.warning(
                        "Servo %d ping failed: %s", sid, self._packet_handler.getTxRxResult(result)
                    )
            logger.info(
                "DynamixelDriver: connected on %s @ %d baud, servos=%s",
                self._port,
                self._baudrate,
                self.servo_ids,
            )
            return True
        except DriverFault:
            raise
        except Exception as exc:
            raise DriverFault(str(exc), "CONNECT_ERROR") from exc

    def _do_disconnect(self) -> None:
        try:
            if self._port_handler:
                self._port_handler.closePort()
        except Exception:
            pass
        self._port_handler = None
        self._packet_handler = None

    def read_servo(self, servo_id: int) -> ServoReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            ph = self._packet_handler
            poh = self._port_handler

            def _read2(addr):
                val, r, _ = ph.read2ByteTxRx(poh, servo_id, addr)
                return val if r == COMM_SUCCESS else 0

            def _read4(addr):
                val, r, _ = ph.read4ByteTxRx(poh, servo_id, addr)
                return val if r == COMM_SUCCESS else 0

            def _read1(addr):
                val, r, _ = ph.read1ByteTxRx(poh, servo_id, addr)
                return val if r == COMM_SUCCESS else 0

            pos_ticks = _read4(_PRESENT_POSITION)
            vel_ticks = _read4(_PRESENT_VELOCITY)
            load_raw = _read2(_PRESENT_LOAD)
            temp = _read1(_PRESENT_TEMP)
            volt = _read2(_PRESENT_VOLTAGE)
            hw_error = _read1(_HARDWARE_ERROR)

            self._record_success()
            return ServoReading(
                servo_id=servo_id,
                position_rad=pos_ticks * _TICK_TO_RAD - math.pi,
                velocity_rads=(
                    (vel_ticks & 0x3FF)
                    * _VEL_UNIT
                    * _RPM_TO_RADS
                    * (-1 if vel_ticks & 0x400 else 1)
                ),
                load_percent=load_raw * _LOAD_UNIT,
                temperature_c=float(temp),
                voltage_v=volt * 0.1,
                error_code=hw_error,
            )
        except Exception as exc:
            self._record_fault("READ_ERROR", str(exc))
            raise DriverFault(str(exc), "READ_ERROR") from exc

    def read_all(self) -> list[ServoReading]:
        return [self.read_servo(sid) for sid in self.servo_ids]

    def write_command(self, cmd: ServoCommand) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            ph = self._packet_handler
            poh = self._port_handler
            pos_ticks = int((cmd.target_position_rad + math.pi) / _TICK_TO_RAD)
            pos_ticks = max(0, min(_DXL_MAX_POS, pos_ticks))
            if cmd.velocity_limit_rads > 0:
                vel_ticks = int(cmd.velocity_limit_rads / (_VEL_UNIT * _RPM_TO_RADS))
                ph.write4ByteTxRx(poh, cmd.servo_id, _GOAL_VELOCITY, vel_ticks)
            ph.write4ByteTxRx(poh, cmd.servo_id, _GOAL_POSITION, pos_ticks)
        except Exception as exc:
            self._record_fault("WRITE_ERROR", str(exc))
            raise DriverFault(str(exc), "WRITE_ERROR") from exc

    def write_commands(self, cmds: list[ServoCommand]) -> None:
        for cmd in cmds:
            self.write_command(cmd)

    def enable_torque(self, servo_id: int, enabled: bool) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        self._packet_handler.write1ByteTxRx(
            self._port_handler, servo_id, _TORQUE_ENABLE, 1 if enabled else 0
        )

    def enable_all_torque(self, enabled: bool) -> None:
        for sid in self.servo_ids:
            self.enable_torque(sid, enabled)
