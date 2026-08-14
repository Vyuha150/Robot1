# Gesture Recognition Failure Analysis

Root cause of "not recognizing different gesture types properly," traced
to specific code.

## What is already correct (and should not be rebuilt)

- **Person assignment is real and correct.** `_assign_persons()`
  (`gesture_node.py:484-518`) maps MediaPipe tracking IDs to
  `bonbon_multi_person_tracker`'s `person_track_id`;
  `GestureEvent.person_track_id` is populated per person; two people
  gesturing simultaneously produce two independent `GestureEvent`
  messages. The brief's specific concern ("gesture recognition may not be
  linked to person_track_id") is **not accurate for gestures that are
  actually classified** — the linkage exists and is tested.
- **Temporal smoothing is real.** `GestureTemporalSmoother` requires a
  majority vote across a sliding window (minimum 2 frames) before firing
  a non-safety gesture (`temporal_smoother.py:87`), specifically to
  prevent one-frame false positives. Safety gestures are exempt from the
  delay by design (they must fire immediately), not by oversight.
- **Safety flagging never touches hardware directly.**
  `GestureSafetyClassifier` only sets fields on the published
  `GestureEvent` (`safety_classifier.py:22-76`); no gesture classifier or
  node calls an actuator or hardware function. This satisfies the brief's
  "stop palm must go to Behavior Engine/Safety Supervisor, not directly
  stop hardware" rule already.

## Root cause: 4 of 16 required gesture types are not actually produced

Across all three classifiers (`hand_gesture_classifier.py`,
`body_gesture_classifier.py`, `head_gesture_classifier.py`), the
following are genuinely implemented and returned: `wave`, `raised_hand`,
`stop_palm`, `pointing_left`, `pointing_right`, `pointing_forward`,
`thumbs_up`, `thumbs_down`, `come_here`, `head_nod_yes`, `head_shake_no`,
`fallen_posture` (the brief's `fallen_or_bent_posture`), and
`unknown_gesture` — **12 of 16**.

Missing:

- **`go_away`** — this is the most misleading gap: the string `"go_away"`
  already exists in `safety_classifier.py:27` (mapped to safety class
  `"retreat"`) and `intent_mapper.py:28` (mapped to intent
  `"retreat_request"`) and is even unit-tested in
  `test_safety_classifier.py:48-49` — but **no classifier ever produces
  the string "go_away" as a classification result**. The downstream
  plumbing exists; the upstream detection does not. A user making a
  "go away" gesture today either gets `unknown_gesture` or is
  misclassified as something else entirely — never `go_away`, no matter
  how clearly the gesture is made.
- **`pointing_at_object`** — distinguishing "pointing at a specific
  nearby object" from generic directional pointing requires fusing
  gesture direction with `bonbon_object_intelligence`'s tracked-object
  positions; that fusion does not exist anywhere in the gesture package.
- **`folded_hands`/`namaste`** — absent from all three classifiers; no
  hand-landmark geometry check for this pose exists.

## Root cause: gesture-config FPS/degraded-mode policy is declared but not enforced

`config/pi_efficiency_profile.yaml` declares
`gesture_recognition: 8 FPS` (rank 9) as part of the shared efficiency
profile, but `bonbon_gesture` does not import or read
`pi_efficiency_profile` anywhere — the FPS limit exists only in the
config file, never applied by the node. `gesture.yaml`'s own
`frame_sample_rate: 3` is a **separate, independent** rate-limiting
mechanism local to the package, disconnected from the shared Pi policy
and from CPU/thermal-triggered degraded mode.

## What this looks like from the outside

A user says "come here" or waves — these work (12/16 gestures do work).
A user makes a "go away" or dismissive gesture expecting the robot to
back off — it silently fails every time, despite the safety/intent
plumbing being fully ready to receive it, because nothing ever emits the
string. This produces an inconsistent user experience ("some gestures
work, others never do") that reads as "gesture recognition doesn't work
properly" even though most of the pipeline (person-linking, smoothing,
safety-routing) is solid.

## Fix scope (Phase 5)

1. **Done.** `go_away` classification added in
   `body_gesture_classifier.py`'s `_is_go_away()`. `_is_beckoning()`
   (come_here) turned out to be an honest, documented stub that always
   returns False -- mirroring it literally would not have fixed
   anything, so this is instead a genuine single-frame static-pose
   proxy (open hand, arm extended sideways/forward away from the torso,
   at or below shoulder height), clearly documented as a best-effort
   proxy for what's fundamentally a motion-based gesture, pending field
   validation this dev sandbox has no camera/dataset access to provide.
   5 new tests in `test_body_classifier.py`.
2. **Deferred, not fabricated.** `pointing_at_object` genuinely needs
   cross-package fusion with `bonbon_object_intelligence`'s tracked-
   object bearings -- a larger, separately-scoped change. Not attempted
   here rather than faked with an ungrounded heuristic.
3. **Done.** `folded_hands`/`namaste` added as
   `HandGestureClassifier.classify_folded_hands()` -- a deliberately
   separate two-hand method (both palms open and pressed close
   together), since every other rule in that class classifies one hand
   at a time and namaste genuinely needs both hands' landmarks at once.
   Wired into `gesture_node.py` (checked before the existing per-hand
   left/right pick) and `intent_mapper.py` (`"greeting_request"`, same
   intent as `wave`). 6 new tests in `test_hand_classifier.py`.
4. **Done**, using what actually exists. `config/pi_perception_profile.yaml`
   (referenced above as "Phase 7's" file) does not exist yet -- checked
   and confirmed absent, not fabricated. `config/pi_efficiency_profile.yaml`
   already has the real `fps_limits.gesture_recognition: 8` value and an
   existing, previously-unused `PiEfficiencyProfile` loader class
   (`bonbon_perception_efficiency`); `bonbon_gesture` is now its first
   real consumer, via `GestureNode._load_pi_wide_fps_cap()` and a new
   `min_interval_sec`/`time_since_last_processed_sec` pair on
   `frame_gate.should_process_frame()` -- a second, independent cap
   alongside `frame_sample_rate`, not a replacement for it. 4 new tests
   in `test_frame_gate.py`. The MediaPipe-unavailable degraded-mode
   fallback this item also asked for already existed
   (`gesture_node.py`'s `on_configure` already falls back to
   `MockBackend` and records it via `GestureHealthMonitor`) -- confirmed,
   not rebuilt.

None of this required changing `PerPersonGestureAssigner`,
`GestureTemporalSmoother`, `GestureSafetyClassifier`, or the pre-existing
tests for the 12 gestures that already worked correctly -- 116 tests pass
across the whole `bonbon_gesture` suite after this fix (up from ~94).
