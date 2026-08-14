"""bonbon_distributed_network_monitor.core.chrony_offset -- pure parser
for `chronyc tracking` output. No subprocess call lives here so this
module is fully unit-testable with fixture text, matching this repo's
established core/-is-pure-logic convention (see e.g.
bonbon_hardware_telemetry.core.threshold_config).

Real `chronyc tracking` output looks like:

    Reference ID    : C0A8010D (192.168.10.13)
    Stratum         : 3
    Ref time (UTC)  : Thu Aug 12 04:45:23 2026
    System time     : 0.000012345 seconds fast of NTP time
    Last offset     : +0.000045678 seconds
    RMS offset      : 0.000034521 seconds
    Frequency       : 12.345 ppm slow
    Residual freq   : +0.002 ppm
    Skew            : 0.456 ppm
    Root delay      : 0.001234567 seconds
    Root dispersion : 0.000987654 seconds
    Update interval : 64.2 seconds
    Leap status     : Normal

Two fields matter for this package's one job: the "System time" line
(the actual current offset from NTP time, signed by fast/slow) and
"Leap status" (chronyd's own synchronised/not-synchronised verdict --
"Not synchronised" happens right after boot before any NTP source has
been reached, and MUST be reported as unknown, never as "offset is
currently 0ms," which is what the field literally reads at that point
and would be a fabricated "all clear").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SYSTEM_TIME_RE = re.compile(
    r"^System time\s*:\s*([\d.]+)\s+seconds\s+(fast|slow)\s+of NTP time", re.MULTILINE
)
_LEAP_STATUS_RE = re.compile(r"^Leap status\s*:\s*(.+)$", re.MULTILINE)

_NOT_SYNCHRONISED = "Not synchronised"


@dataclass(frozen=True)
class ChronyTrackingResult:
    parsed: bool
    synchronised: bool
    offset_ms: float | None  # None when parsed=False or not synchronised
    leap_status: str | None
    raw_error: str | None = None


def parse_chronyc_tracking(output: str) -> ChronyTrackingResult:
    """Parse real `chronyc tracking` stdout. Never raises -- malformed or
    empty input is reported as parsed=False, not a fabricated 0 offset."""
    if not output or not output.strip():
        return ChronyTrackingResult(
            parsed=False,
            synchronised=False,
            offset_ms=None,
            leap_status=None,
            raw_error="empty chronyc output",
        )

    leap_match = _LEAP_STATUS_RE.search(output)
    if leap_match is None:
        return ChronyTrackingResult(
            parsed=False,
            synchronised=False,
            offset_ms=None,
            leap_status=None,
            raw_error="could not find 'Leap status' line in chronyc output",
        )
    leap_status = leap_match.group(1).strip()
    synchronised = leap_status != _NOT_SYNCHRONISED

    if not synchronised:
        return ChronyTrackingResult(
            parsed=True,
            synchronised=False,
            offset_ms=None,
            leap_status=leap_status,
        )

    system_time_match = _SYSTEM_TIME_RE.search(output)
    if system_time_match is None:
        return ChronyTrackingResult(
            parsed=False,
            synchronised=True,
            offset_ms=None,
            leap_status=leap_status,
            raw_error="could not find 'System time' line in chronyc output",
        )

    magnitude_sec = float(system_time_match.group(1))
    direction = system_time_match.group(2)
    signed_sec = magnitude_sec if direction == "fast" else -magnitude_sec

    return ChronyTrackingResult(
        parsed=True,
        synchronised=True,
        offset_ms=signed_sec * 1000.0,
        leap_status=leap_status,
    )


def unavailable_result(reason: str) -> ChronyTrackingResult:
    """For when chronyc itself couldn't be run at all (not installed,
    permission denied, timed out) -- the node layer's subprocess-failure
    path constructs this, not this module."""
    return ChronyTrackingResult(
        parsed=False, synchronised=False, offset_ms=None, leap_status=None, raw_error=reason
    )
