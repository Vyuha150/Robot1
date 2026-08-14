"""GAP-E12 regression coverage: gesture recognition must gate on person
presence (a VAD-equivalent event gate), not just frame-rate throttle."""

from __future__ import annotations

import unittest

from bonbon_gesture.logic.frame_gate import should_process_frame


class TestShouldProcessFrame(unittest.TestCase):
    def test_in_flight_always_skips(self):
        self.assertFalse(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=True,
                gate_on_person_presence=False,
                persons_topic_ever_received=True,
                any_person_present=True,
            )
        )

    def test_off_beat_frame_skips(self):
        self.assertFalse(
            should_process_frame(
                frame_counter=2,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=False,
                persons_topic_ever_received=True,
                any_person_present=True,
            )
        )

    def test_on_beat_frame_with_gate_disabled_processes(self):
        self.assertTrue(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=False,
                persons_topic_ever_received=True,
                any_person_present=False,
            )
        )

    def test_gate_enabled_no_person_present_skips(self):
        # The core GAP-E12 behavior: nobody in view -> skip, once we
        # genuinely know that (persons topic has reported at least once).
        self.assertFalse(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=True,
                persons_topic_ever_received=True,
                any_person_present=False,
            )
        )

    def test_gate_enabled_person_present_processes(self):
        self.assertTrue(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=True,
                persons_topic_ever_received=True,
                any_person_present=True,
            )
        )

    def test_gate_enabled_before_first_persons_message_does_not_block(self):
        # Startup race: no PersonStateArray has arrived yet -- must not
        # assume "nobody present" and permanently block gesture
        # recognition before the persons topic ever delivers anything.
        self.assertTrue(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=True,
                persons_topic_ever_received=False,
                any_person_present=False,
            )
        )

    def test_zero_sample_rate_never_processes(self):
        self.assertFalse(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=0,
                in_flight=False,
                gate_on_person_presence=False,
                persons_topic_ever_received=True,
                any_person_present=True,
            )
        )

    # ── Pi-wide FPS cap (Phase 5 fix scope item 4) ─────────────────────

    def test_min_interval_disabled_by_default_processes(self):
        self.assertTrue(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=False,
                persons_topic_ever_received=True,
                any_person_present=True,
            )
        )

    def test_min_interval_not_yet_elapsed_skips(self):
        self.assertFalse(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=False,
                persons_topic_ever_received=True,
                any_person_present=True,
                min_interval_sec=0.125,
                time_since_last_processed_sec=0.05,
            )
        )

    def test_min_interval_elapsed_processes(self):
        self.assertTrue(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=False,
                persons_topic_ever_received=True,
                any_person_present=True,
                min_interval_sec=0.125,
                time_since_last_processed_sec=0.20,
            )
        )

    def test_min_interval_zero_ignores_elapsed_time(self):
        # min_interval_sec<=0.0 means the Pi-wide cap hasn't been loaded
        # yet (or is disabled) -- must not gate on a real elapsed time in
        # that state, even a very small one.
        self.assertTrue(
            should_process_frame(
                frame_counter=3,
                frame_sample_rate=3,
                in_flight=False,
                gate_on_person_presence=False,
                persons_topic_ever_received=True,
                any_person_present=True,
                min_interval_sec=0.0,
                time_since_last_processed_sec=0.001,
            )
        )


if __name__ == "__main__":
    unittest.main()
