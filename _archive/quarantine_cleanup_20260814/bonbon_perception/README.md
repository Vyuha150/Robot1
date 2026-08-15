# ⚠️ QUARANTINED — bonbon_perception

**This package is not built, launched, or used anywhere in this repository.**
It is kept for reference only.

## Why

An efficiency audit (2026-06-30) found this package to be a fully orphaned
duplicate of `bonbon_vision`'s detection and face pipeline:

- Its own YOLO/HOG person detector (`detection_node.py`), running independent
  inference on the same `/bonbon/vision/camera/color/image_raw` topic
  `bonbon_vision`'s `vision_node` already consumes.
- Its own face pipeline (`face_node.py` — OpenCV-LBP/DeepFace/InsightFace
  backends), independently duplicating `bonbon_vision`'s `face_pipeline.py`.
- **Zero dependents anywhere in the repository** — no package declares it in
  `package.xml`, no Python module imports from it (confirmed by repo-wide
  search), and it was never included in `bonbon_bringup`.

Running it alongside `bonbon_vision` would silently double camera processing
and model inference load, and produce a second, conflicting set of person
track IDs — exactly the "duplicated camera pipeline" / "duplicated model
inference" failure mode the project's efficiency rules explicitly forbid.

## What was done

Rather than delete the code outright, it was **quarantined**:

1. `launch/perception.launch.py` → `launch/perception.launch.py.disabled`
   (excluded from `setup.py`'s install glob — `ros2 launch` can no longer
   discover it).
2. `setup.py`'s `console_scripts` entry points were removed — `ros2 run
   bonbon_perception detection_node` / `face_node` no longer resolve.
3. This README and a banner at the top of `detection_node.py`/`face_node.py`
   mark the deprecation for anyone reading the source directly.

The package still builds (so it doesn't break `colcon build --packages-up-to`
chains that might reference it), but produces no runnable artifact.

## If you need this code back

Don't. Use `bonbon_vision` — it already does both person detection and face
recognition, actively maintained, in bringup, with the multi-person
lifecycle/identity layer (`bonbon_multi_person_tracker`) built on top of it.
If something specific in this package's detector/recognizer backends is
genuinely missing from `bonbon_vision` (e.g. a detector model variant), port
*that specific piece* into `bonbon_vision`'s existing detector interface —
do not re-enable this package wholesale.
