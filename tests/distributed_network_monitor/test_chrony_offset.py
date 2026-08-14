"""bonbon_distributed_network_monitor.core.chrony_offset -- exercises
the pure `chronyc tracking` parser against real-shaped sample output
(synchronised, not-yet-synchronised, and malformed/empty input)."""

from __future__ import annotations

import unittest

from bonbon_distributed_network_monitor.core.chrony_offset import (
    parse_chronyc_tracking,
    unavailable_result,
)

_SYNCHRONISED_FAST = """\
Reference ID    : C0A8010D (192.168.10.13)
Stratum         : 3
Ref time (UTC)  : Thu Aug 12 04:45:23 2026
System time     : 0.123000000 seconds fast of NTP time
Last offset     : +0.000045678 seconds
RMS offset      : 0.000034521 seconds
Frequency       : 12.345 ppm slow
Residual freq   : +0.002 ppm
Skew            : 0.456 ppm
Root delay      : 0.001234567 seconds
Root dispersion : 0.000987654 seconds
Update interval : 64.2 seconds
Leap status     : Normal
"""

_SYNCHRONISED_SLOW = _SYNCHRONISED_FAST.replace(
    "System time     : 0.123000000 seconds fast of NTP time",
    "System time     : 0.250000000 seconds slow of NTP time",
)

_NOT_SYNCHRONISED = """\
Reference ID    : 00000000 ()
Stratum         : 0
Ref time (UTC)  : Thu Jan 01 00:00:00 1970
System time     : 0.000000000 seconds fast of NTP time
Last offset     : +0.000000000 seconds
RMS offset      : 0.000000000 seconds
Frequency       : 0.000 ppm slow
Residual freq   : +0.000 ppm
Skew            : 0.000 ppm
Root delay      : 1.000000000 seconds
Root dispersion : 1.000000000 seconds
Update interval : 0.0 seconds
Leap status     : Not synchronised
"""


class TestParseChronycTracking(unittest.TestCase):
    def test_synchronised_fast_offset_is_positive_ms(self):
        result = parse_chronyc_tracking(_SYNCHRONISED_FAST)
        self.assertTrue(result.parsed)
        self.assertTrue(result.synchronised)
        self.assertAlmostEqual(result.offset_ms, 123.0, places=3)
        self.assertEqual(result.leap_status, "Normal")

    def test_synchronised_slow_offset_is_negative_ms(self):
        result = parse_chronyc_tracking(_SYNCHRONISED_SLOW)
        self.assertTrue(result.parsed)
        self.assertAlmostEqual(result.offset_ms, -250.0, places=3)

    def test_not_synchronised_reports_no_offset_not_zero(self):
        # The literal "System time" line reads 0.000000000 here -- must
        # NOT be reported as "offset is 0ms" (a fabricated all-clear).
        result = parse_chronyc_tracking(_NOT_SYNCHRONISED)
        self.assertTrue(result.parsed)
        self.assertFalse(result.synchronised)
        self.assertIsNone(result.offset_ms)
        self.assertEqual(result.leap_status, "Not synchronised")

    def test_empty_output_is_unparsed(self):
        result = parse_chronyc_tracking("")
        self.assertFalse(result.parsed)
        self.assertIsNone(result.offset_ms)
        self.assertIsNotNone(result.raw_error)

    def test_garbage_output_is_unparsed_not_fabricated(self):
        result = parse_chronyc_tracking("506 Cannot talk to daemon\n")
        self.assertFalse(result.parsed)
        self.assertIsNone(result.offset_ms)

    def test_unavailable_result_helper(self):
        result = unavailable_result("chronyc: command not found")
        self.assertFalse(result.parsed)
        self.assertFalse(result.synchronised)
        self.assertEqual(result.raw_error, "chronyc: command not found")


if __name__ == "__main__":
    unittest.main()
