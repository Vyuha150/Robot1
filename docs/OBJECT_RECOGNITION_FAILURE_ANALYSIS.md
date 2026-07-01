# Object Recognition Failure Analysis

Root cause of "not recognizing a wide range of real-world objects,"
traced to specific code, not assumed.

## Root cause 1: the detector only knows 80 generic COCO classes

`bonbon_vision`'s `YoloDetector` wraps `ultralytics.YOLO` directly
(`yolo_detector.py:46-90`) with no custom class layer. COCO's 80 classes
cover generic categories (`person`, `chair`, `bottle`, `laptop`, `cell
phone`, `backpack`, `dining table`) but have **no concept of**:
`wheelchair_user`, `hospital_bed`, `reception_counter`, `lift_button`,
`room_number_sign`, `ID_card`, `medicine_box`, `food_packet`,
`wet_floor_sign`, `trolley`, `ramp` — none of these exist in COCO's
taxonomy, so YOLO structurally cannot output them, no matter what
confidence threshold is set. This is not a bug in the detector; it's a
capability the current model was never given. Requesting these classes
today returns nothing, silently — which is the correct behavior (never
hallucinate a class the model doesn't have) but looks like "not
recognizing objects" from the outside.

## Root cause 2: no Hailo/AI HAT acceleration in the live pipeline

`bonbon_ai_runtime`'s `RuntimeSelector`/`HailoRuntime`/`CPUONNXRuntime`
abstraction exists and is tested (30 tests), but **no production code
path uses it** — `bonbon_vision` loads YOLO directly via ultralytics,
never through `RuntimeSelector`. On a Raspberry Pi 5 without Hailo
acceleration, YOLO inference runs on the ARM CPU, which is both slow
(reducing effective detection rate/coverage under the Pi efficiency
profile's frame-skipping) and never gets the accuracy/speed benefit a
properly quantized Hailo model would provide. This compounds root cause 1
— even the 80 classes YOLO *can* detect are detected less reliably under
Pi CPU load.

## Root cause 3: no verification or class-mapping strategy for near-misses

The brief's required fallback strategies (map to nearest base class, use
a CLIP/SigLIP-style verifier, use OCR for signs/documents, mark as
unsupported-but-configurable) are **none of them implemented**. A
`wheelchair` in frame is either silently misclassified as whatever COCO
class the raw model happens to fire on (no mapping/verification step
exists to catch or correct this) or not detected at all. OCR exists as a
hook (`ocr_hook.py`) with an eligible-class set (`sign`, `document`,
`book`, `menu`, `label`) but is **disabled by default**
(`enable_ocr: false` in `object_intelligence_params.yaml`) and — since
none of those 5 classes are ever produced by base YOLO either — has
nothing to trigger on even when enabled.

## Root cause 4: no dashboard visibility into any of the above

There is no endpoint or metric surfacing "supported classes: 80 (COCO)",
"unsupported class requested: wheelchair_user (0 detections, ever)", or
"runtime: CPU (Hailo never attempted)" — so today this entire failure
mode is invisible to an operator; it looks like the robot "just doesn't
see things," with no diagnostic trail explaining why.

## What is NOT broken

Confidence thresholding, deduplication, object permanence (remembering an
object briefly after occlusion), and the tracking state machine are all
implemented and tested (36/36 tests pass) — these are not the source of
the complaint. The failure is entirely in **class coverage** and
**runtime acceleration**, not in the tracking/calibration layer built on
top of whatever the detector produces.

## Fix scope (Phase 2)

1. Wire `bonbon_vision`'s detector construction through
   `bonbon_ai_runtime.RuntimeSelector` so Hailo is actually attempted on
   a Pi + AI HAT, with the same honest CPU-fallback-with-reason contract
   already proven in `bonbon_ai_runtime`'s own tests.
2. Add an `ObjectClassRegistry` mapping the ~30 required service-
   environment classes to a strategy per class: direct COCO class,
   nearest-base-class alias, OCR-eligible (enabled), or
   explicitly-unsupported (configurable, never hallucinated).
3. Add an `ObjectVerificationManager` for the classes that need a second
   check before being reported (e.g. alias matches).
4. Publish the missing dashboard-facing metrics: supported-class count,
   active detections, low-confidence count, inference latency/FPS,
   fallback reason.

None of this requires changing `ObjectPermanenceTracker`,
`ObjectConfidenceCalibrator`, or the existing 36 tests — they are correct
and are extended, not replaced.
