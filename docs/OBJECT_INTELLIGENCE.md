# Object Intelligence

Package: [`bonbon_object_intelligence`](../ros2_ws/src/bonbon_object_intelligence/README.md)

## Purpose

Adds object permanence, confidence calibration, OCR, and depth association on
top of `bonbon_vision`'s existing detection output. Answers "is this object
still there even though I can't see it right now," "should I trust this
detection," and "what does this sign say" — none of which `bonbon_vision`'s
own embedded tracker does (it evicts a track the instant it's missed once).

## Architecture

```
bonbon_vision/vision_node                bonbon_object_intelligence/object_intelligence_node
   │ /bonbon/vision/objects                  │
   │ (DetectedObjectArray)                   │
   └──────────────────────────────────────────▶ ObjectConfidenceCalibrator
                                                   (dedupe → calibrate → reject)
                                                ▼
                                              ObjectPermanenceTracker
                                                (visible → occluded → memory → lost)
                                                ▼
                                              /bonbon/objects/tracked (TrackedObject)
```

No new camera pipeline, no re-detection — this package consumes
`/bonbon/vision/objects` only.

## ROS2 interface

| Topic/Service | Type | Direction |
|---|---|---|
| `/bonbon/vision/objects` | `DetectedObjectArray` | sub |
| `/bonbon/safety/state` | `SafetyState` | sub |
| `/bonbon/objects/tracked` | `TrackedObject` | pub |
| `/bonbon/objects/object_intelligence_node/health` | `ModuleHealth` | pub |
| `~/health_check` | `bonbon_srvs/HealthCheck` | service |

## Configuration

See [`config/object_intelligence_params.yaml`](../ros2_ws/src/bonbon_object_intelligence/bonbon_object_intelligence/config/object_intelligence_params.yaml).
Key knobs: `occlusion_grace_sec` (2.0), `memory_grace_sec` (15.0),
`max_objects` (50, resource bound), `rejection_threshold` (0.3),
`small_object_area_px` / `small_object_confidence_floor`, `enable_ocr` (off
by default — `MockOCRBackend` never fabricates text).

## Example

A chair detected at 85% confidence, briefly hidden by a passing person for
1.5 seconds, then visible again: the tracker reports `occluded` during the
gap (never re-created as a new object) and returns to `visible` with the
same `object_track_id` once redetected.

## Failure modes

| Failure | Behavior |
|---|---|
| `/bonbon/vision/objects` stale | Cycle runs with zero detections — objects age toward `occluded`/`memory`/`lost` rather than staying falsely visible. |
| Duplicate/overlapping detections (YOLO anchor-box overlap) | Collapsed via IoU to the single highest-confidence detection. |
| Small object, naturally lower confidence | Floored, not rejected, purely for being small. |
| No depth or fused 3D position available | Falls back to bearing-only placement at a nominal 1 m — never a fabricated precise position. |

## Tests

36 tests across 5 core modules (`tests/test_object_permanence_tracker.py`,
`test_confidence_calibrator.py`, `test_ocr_hook.py`,
`test_object_memory_hook.py`, `test_depth_association.py`). Plus 3 of the 25
cross-package scenarios in [`tests/scenarios/`](../tests/scenarios/test_multi_person_perception_scenarios.py)
(object detection success, tracking through occlusion, low-confidence
rejection).

## Performance tuning

Target: **object detection/tracking 5–15 FPS configurable**
(`publish_rate_hz`). See [performance_tuning.md](performance_tuning.md) for
the measured benchmark and how to adjust `max_objects`/grace windows for your
hardware.

## Troubleshooting

- **Objects flicker between visible/occluded constantly** — `occlusion_grace_sec`
  is likely too short relative to your detector's actual miss rate; raise it.
- **Two real, distinct objects merge into one track** — `max_match_distance_m`
  (constructor default 0.5 m) may be too generous for closely-spaced small
  objects; this isn't exposed as a YAML param yet — adjust in code if needed.
- **`is_small_object` true for everything** — check `small_object_area_px`
  against your camera's actual resolution; the default (900 px², ~30×30 px)
  assumes a 640×480 frame.
