# bonbon_object_intelligence

Object permanence, confidence calibration, OCR hook, and depth association
for the BonBon service robot. Consumes `bonbon_vision`'s existing
`DetectedObjectArray` output — does not re-run object detection.

## Why this package exists

`bonbon_vision`'s own embedded tracker (`vision_node._SimpleTracker`) evicts
an object the moment it's missed for `max_lost` frames — there is no concept
of "this is probably just occluded, not actually gone," no confidence
calibration, no OCR, and no depth-derived 3D position when the detector
itself hasn't fused one. This package adds exactly those, layered on top of
`/bonbon/vision/objects`.

## Core modules (`bonbon_object_intelligence/core/`, no rclpy)

| Module | Responsibility | Honest limitation |
|---|---|---|
| `object_permanence_tracker.py` | `visible → occluded → memory → lost` lifecycle (mirrors `bonbon_multi_person_tracker`'s FSM shape) | No re-identification by appearance after `lost` — a re-detection always gets a new `object_track_id`. |
| `confidence_calibrator.py` | Class-specific confidence adjustment, small-object confidence floor, near-duplicate collapsing | **Not a fitted statistical calibration model** — no labeled calibration dataset exists in this repo. This is a configurable adjustment hook, not Platt scaling/isotonic regression. |
| `ocr_hook.py` | OCR backend interface + mock, gated to sign/document-like classes | `MockOCRBackend` always returns empty text — no real OCR engine (pytesseract/EasyOCR) is a dependency here yet. |
| `object_memory_hook.py` | Interface + in-memory store for "what did I last see, where" | Real persistence into `bonbon_data_stores` is a separate integration this package doesn't own — the interface is the seam. |
| `depth_association.py` | 2D bbox + depth → 3D position via the same pinhole-camera convention as `bonbon_hal.UsbCameraDriver` | Only used as a fallback when `bonbon_vision` hasn't itself populated `DetectedObject.position_3d`. |

## ROS2 interface

**Subscribes:** `/bonbon/vision/objects` (`DetectedObjectArray`), `/bonbon/safety/state`.
**Publishes:** `/bonbon/objects/tracked` (`TrackedObject`), health.
**Services:** `~/health_check`.

## Failure handling

| Failure | Behavior |
|---|---|
| `/bonbon/vision/objects` stale | Cycle runs with zero detections — objects age toward `occluded`/`memory`/`lost` rather than staying falsely visible off a frozen frame. |
| Duplicate/overlapping detections (known YOLO anchor-box failure mode) | Collapsed to the single highest-confidence detection per class via IoU. |
| Small object (low confidence due to scale, not necessarily wrong) | Confidence floored rather than rejected — see "small object mode" above. |
| `DetectedObject.depth_m` is NaN and no fused `position_3d` | Falls back to bearing-only placement at a nominal 1 m depth — never a fabricated precise position. |

## Tests

```
tests/test_object_permanence_tracker.py   9 tests
tests/test_confidence_calibrator.py      12 tests
tests/test_ocr_hook.py                    4 tests
tests/test_object_memory_hook.py          7 tests
tests/test_depth_association.py           4 tests
```
Run: `python -m pytest tests/ -q` (no rclpy required).

## Performance target

Object detection/tracking **5–15 FPS configurable** (`publish_rate_hz`). The
tracker itself is O(detections × tracked objects) per cycle, bounded by
`max_objects` (default 50) — far under budget; the actual detection latency
is owned by `bonbon_vision`, not this package.
