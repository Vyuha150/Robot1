"""frame_gate — GAP-E12 fix: an event gate for gesture recognition,
analogous to speech's VAD gate.

Before this fix, gesture_node.py's only rate control was a modulo-N frame
counter (frame_sample_rate) -- it ran gesture inference on every Nth frame
unconditionally, including frames where no person is anywhere in view.
This module adds the missing "is there anyone to gesture at all" check,
the same class of event-gating bonbon_speech_ai's VAD gate and
bonbon_vision's FrameThrottler already apply to their own modalities.

Pure Python, no rclpy dependency -- fully unit-testable.
"""

from __future__ import annotations


def should_process_frame(
    *,
    frame_counter: int,
    frame_sample_rate: int,
    in_flight: bool,
    gate_on_person_presence: bool,
    persons_topic_ever_received: bool,
    any_person_present: bool,
) -> bool:
    """Returns True if this frame should be dispatched for gesture
    inference.

    `persons_topic_ever_received` distinguishes "no PersonStateArray has
    arrived yet" (startup race -- must not gate, or gesture recognition
    would never run before the first persons message) from "a
    PersonStateArray arrived and it was empty" (someone genuinely
    checked and nobody is there -- safe to gate). Matches this repo's
    established "never seen -> don't assume, not never seen -> assume
    absent" honesty pattern (see HeartbeatMonitor's own docstring).
    """
    if in_flight:
        return False
    if frame_sample_rate <= 0 or (frame_counter % frame_sample_rate) != 0:
        return False
    if gate_on_person_presence and persons_topic_ever_received and not any_person_present:
        return False
    return True
