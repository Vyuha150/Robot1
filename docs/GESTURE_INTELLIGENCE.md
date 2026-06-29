# Gesture Intelligence

Package: [`bonbon_gesture`](../ros2_ws/src/bonbon_gesture/README.md) (extended, not duplicated)

## Purpose

Recognises hand/body/head gestures and — the genuinely new capability added
in this round — correctly attributes each gesture to the right person when
multiple people are in frame simultaneously. An audit found `bonbon_gesture`
already implemented almost the entire "gesture intelligence" brief (the
vocabulary, classifiers, temporal smoothing); creating a parallel
`bonbon_gesture_intelligence` package would have duplicated it. The one real
gap — multi-person assignment — is what this round added.

## Architecture

```
bonbon_vision/camera + bonbon_multi_person_tracker/persons/tracks
   │                                  │
   ▼                                  ▼
GestureNode: HandClassifier + BodyClassifier + HeadClassifier
   │
   ▼
GestureTemporalSmoother (majority vote, cooldown, temporal_stability)
   │
   ▼
GesturePersonAssigner ── matches each landmark set's frame position
   │                      to a tracked person's predicted bearing
   ▼
/bonbon/gesture/events (GestureEvent: person_track_id, hand_side, body_part,
                         recommended_intent, temporal_stability)
```

### Multi-person assignment

Neither `PersonState` nor `PersonTrack` carries a populated per-frame pixel
bounding box — only a 3D position. Rather than inventing a fictional
depth/projection pipeline, `GesturePersonAssigner` uses the one honest signal
available on both sides: a tracked person's bearing (`atan2(y, x)`, the same
convention `bonbon_spatial` uses) predicts where they should appear
horizontally in frame given the camera's `hfov_deg`; each landmark set is
matched to its nearest-bearing person within a tolerance. Count mismatches
or out-of-tolerance matches are left unassigned, never guessed.

## ROS2 interface

| Topic/Service | Type | Direction |
|---|---|---|
| `/bonbon/vision/camera/color/image_raw` | `sensor_msgs/Image` | sub |
| `/bonbon/vision/persons` | `PersonStateArray` | sub |
| `/bonbon/persons/tracks` | `PersonTrack` | sub |
| `/bonbon/safety/state` | `SafetyState` | sub |
| `/bonbon/gesture/events` | `GestureEvent` | pub |
| `/bonbon/gesture/status`, `/bonbon/diagnostics/events` | `std_msgs/String` (JSON) | pub |
| `/bonbon/gesture/health_check`, `/bonbon/gesture/set_enabled` | services | service |

## Configuration

See [`config/gesture.yaml`](../ros2_ws/src/bonbon_gesture/config/gesture.yaml).
New knobs for this round: `camera_hfov_deg` (60.0, keep in sync with the
active camera driver), `person_assign_max_x_norm_delta` (0.35).

## Gesture vocabulary

`wave, raised_hand, stop_palm, pointing_left, pointing_right,
pointing_forward, come_here, go_away, thumbs_up, thumbs_down,
head_nod_yes, head_shake_no, fallen_posture, unknown`.

## Example

Two people, one on each side of frame. Person A (bearing +20°, left side of
image) raises a stop_palm; Person B (bearing −20°, right side) waves. The
assigner matches each landmark set to its own nearest-bearing person — the
stop_palm event carries A's `person_track_id`, never B's.

## Failure modes / bugs fixed this round

| Issue | Fix |
|---|---|
| `_get_person_position`'s substring-match fallback (`pid.endswith(str(tracking_id))`) could cross-match the wrong person (tracking_id=3 matching "person_13") | Removed; now prefers the authoritative `PersonTrack` position when assignment succeeded, exact-match only otherwise. |
| `GestureTemporalSmoother.notify_person_lost()` existed but was never called | Wired to `bonbon_multi_person_tracker`'s `left_scene` event — a person who walks away mid-gesture now gets a proper trailing `just_ended` event instead of leaking smoother state forever. |
| `GestureIntentMapper` existed but was never wired to the publish path | Now populates `GestureEvent.recommended_intent`. |

## Tests

84 pre-existing + 47 new this round (`test_person_assigner.py`,
`test_body_part_classifier.py`, `test_temporal_smoother.py` — the latter two
had zero direct unit tests before, only indirect integration coverage).
Plus 4 of the 25 cross-package scenarios (gesture linked to correct person,
stop palm safety relevance, pointing assignment, simultaneous multi-person
gestures).

## Performance tuning

Target: **gesture update ≤ 150 ms**. See [performance_tuning.md](performance_tuning.md).
Tune `frame_sample_rate` (process every Nth frame) and
`processing_timeout_sec` for CPU-constrained hardware (e.g. Raspberry Pi).

## Troubleshooting

- **Gestures attributed to the wrong person** — verify `camera_hfov_deg`
  matches your actual camera; a wrong FOV skews the bearing→pixel prediction.
- **No assignment at all (`person_track_id` always empty)** — confirm
  `bonbon_multi_person_tracker` is running and publishing `/bonbon/persons/tracks`;
  the assigner needs at least one tracked person to match against.
- **Two close-together people's gestures swap** — increase camera
  resolution/FOV precision or reduce `person_assign_max_x_norm_delta` to
  tighten the match tolerance (at the cost of more unassigned gestures).
