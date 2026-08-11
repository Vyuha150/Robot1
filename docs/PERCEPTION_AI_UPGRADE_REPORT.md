# Perception AI Upgrade Report

Phase 7/14. Covers object/person detection, pose estimation, face
recognition registry entries and `bonbon_perception_ai`'s one new file
this pass (`hospital_class_registry.py`).

## GAP-2: three competing object-detection implementations — registered, not consolidated

`docs/AI_MODEL_GAP_ANALYSIS.md` GAP-2 found three real, independent
implementations already in this codebase: `bonbon_vision.YoloDetector`,
`bonbon_vision.ObjectDetectorRuntimeAdapter`, and a raw Ultralytics path.
Rather than arbitrarily crowning one "the" default without the code
consolidation GAP-2 calls for (real cross-package surgery, higher risk
than registry work, deferred by deliberate scope decision), this pass
registered all three honestly in `config/models/model_registry.yaml`:
`vision_hailo_yolo` → `vision_cpu_onnx_runtime_adapter` →
`vision_ultralytics_direct` → `vision_mock`. **No entry is
`enabled_by_default`** — confirmed structurally correct in
`tests/perception_ai/test_hailo_runtime_selection.py::TestObjectPersonPoseHaveNoSilentDefault`
(2 tests: `object_detection`/`person_detection` selection both correctly
resolve to `active_model_id=None, degraded=True`, never a guessed
answer).

## Real bug found and fixed this pass: Hailo detection was permanently broken

`model_runtime_selector.py`'s `_check_hailo_available()` imported a
module-level function `runtime_available` from
`bonbon_ai_runtime.hailo_device_detector` that has **never existed**
there — it's a *method* on the `HailoDeviceDetector` class, not a
module-level function. The resulting `ImportError` was silently caught by
the existing `try/except`, so `_check_hailo_available` returned `False`
**unconditionally**, on every machine, regardless of whether real Hailo
hardware was actually present. This defeated the module's own stated
purpose ("delegates vision hardware detection to the existing
bonbon_ai_runtime.hailo_device_detector"). Fixed to
`HailoDeviceDetector().detect().usable` — the same real, no-mock API
`tests/production/_hardware_gates.py` already uses. Regression-tested in
`tests/perception_ai/test_hailo_runtime_selection.py::test_hailo_checker_delegates_to_bonbon_ai_runtime_not_a_second_implementation`.
This bug would have silently prevented the AI HAT+2's vision acceleration
from ever activating on real Pi-2/Pi-3 hardware, even once installed —
now fixed before any real hardware deployment depended on it.

## Hospital class allowlist (`hospital_class_registry.py`, this pass's one new file)

`SUPPORTED_CLASSES` = 12 generic COCO classes relevant to a hospital
lobby (person, chair, bench, backpack, etc.) + 6 hospital-specific
classes (wheelchair, stretcher, iv_stand, hospital_bed, walker, crutches)
— the latter explicitly flagged as target taxonomy only, not backed by any
trained model in this pass (no custom/fine-tuned detector exists yet).
`filter_detections()` **drops** (never relabels or guesses) any detection
outside this allowlist, enforcing "unsupported classes must never be
hallucinated." This registry does not own detection itself — it is the
allowlist any of the three real detector implementations' raw output
should be filtered through. Tested in
`tests/perception_ai/test_object_model_fallback.py::TestHospitalClassAllowlist`
(3 tests).

## Status on this environment

No Hailo hardware, no `onnxruntime`/`ultralytics` installed → every
vision entry (object/person/pose/face) correctly reports unavailable.
Confirmed live via `ModelRuntimeSelector.is_available()` for every
`hailo_8`/`hailo_10h` entry in
`tests/perception_ai/test_hailo_runtime_selection.py::test_every_hailo_entry_reports_unavailable_on_this_sandbox`.

## Verdict: **PARTIAL** (registry/allowlist correct and tested; the Hailo detection bug fix is a real production-relevant correctness fix) / **BLOCKED** (real detection requires a real camera — OAK-D Lite per the BOM — and either a real Hailo device or the object-detector consolidation GAP-2 calls for; neither exists in this pass).
