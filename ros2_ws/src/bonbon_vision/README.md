# bonbon_vision

Production-grade vision module for the **Bonbon** service robot.

Implements the full camera intelligence pipeline as a ROS2 Humble `LifecycleNode`:  
YOLO object detection · face detection & recognition · multi-person tracking ·  
privacy-safe anonymisation · configurable frame rate · structured health reporting.

---

## Contents

- [Architecture](#architecture)
- [Topics](#topics)
- [Parameters](#parameters)
- [Backends](#backends)
- [Privacy Mode](#privacy-mode)
- [Quick Start](#quick-start)
- [Testing](#testing)
- [Benchmarks](#benchmarks)
- [Design Decisions](#design-decisions)
- [Directory Layout](#directory-layout)

---

## Architecture

```
Camera HAL node
  │  /bonbon/vision/camera/color/image_raw  (sensor_msgs/Image BGR8)
  │  /bonbon/vision/camera/depth/image_raw  (sensor_msgs/Image 32FC1)
  ▼
VisionNode (LifecycleNode)
  │
  ├─ FrameThrottler      Token-bucket rate limiter (target detection_rate_hz)
  ├─ FrameProcessor      CLAHE low-light enhancement · resize · quality gate
  ├─ BaseDetector        Timeout wrapper + degraded-mode guard
  │    └─ YoloDetector   ultralytics YOLOv8 — 80 COCO classes
  │    └─ MockDetector   CI / simulation — zero dependency
  ├─ FacePipeline        Two-stage detect + recognise with per-stage timeout
  │    ├─ OpenCV DNN     ResNet-SSD Caffe face detector
  │    ├─ InsightFace    ArcFace — combined detect + embed
  │    └─ DeepFace       Facenet512 — recognition only
  ├─ PrivacyGuard        Gaussian blur / pixelation on annotated images ONLY
  └─ _SimpleTracker      IoU greedy assignment · EMA position smoothing
         │
         ▼ /bonbon/vision/objects  (DetectedObjectArray)
         ▼ /bonbon/vision/persons  (PersonStateArray)
         ▼ /bonbon/vision/annotated_image (optional debug image)
         ▼ /bonbon/vision/vision_node/health (ModuleHealth → Safety Supervisor)
```

### Key design rules

| Rule | How it is enforced |
|---|---|
| No model path is hardcoded | All paths declared as ROS2 parameters; `validate()` raises if backend=yolo but path="" |
| Original frames are never modified | `PrivacyGuard.anonymise()` always works on a copy; inference frame is untouched |
| Inference never blocks the ROS2 timer | `BaseDetector` uses `ThreadPoolExecutor` with `future.result(timeout=N)` |
| Degraded startup is supported | `allow_degraded=True` → node starts with no model; publishes empty results |
| All config is typed | Nested `@dataclass` hierarchy with `validate()` on each level |
| Structured logging | Every log line uses `key=value` pairs (`stage=`, `latency_ms=`, `error=`) |

---

## Topics

### Subscribed

| Topic | Type | QoS | Description |
|---|---|---|---|
| `/bonbon/vision/camera/color/image_raw` | `sensor_msgs/Image` | BEST_EFFORT depth=2 | BGR8 colour frame from HAL camera node |
| `/bonbon/vision/camera/depth/image_raw` | `sensor_msgs/Image` | BEST_EFFORT depth=2 | 32FC1 aligned depth in metres |

### Published

| Topic | Type | QoS | Description |
|---|---|---|---|
| `/bonbon/vision/objects` | `bonbon_msgs/DetectedObjectArray` | RELIABLE depth=5 | Multi-class YOLO detections with depth + bearing |
| `/bonbon/vision/persons` | `bonbon_msgs/PersonStateArray` | RELIABLE depth=5 | Tracked persons with face ID (if recognised) |
| `/bonbon/vision/annotated_image` | `sensor_msgs/Image` | BEST_EFFORT depth=1 | Debug annotated image (disabled by default) |
| `/bonbon/vision/vision_node/health` | `bonbon_msgs/ModuleHealth` | RELIABLE TL depth=1 | Health heartbeat consumed by Safety Supervisor watchdog |

---

## Parameters

All parameters are declared at node startup with safe defaults.  
Override via launch file, YAML param file, or CLI `--ros-args -p name:=value`.

### Top-level

| Parameter | Type | Default | Description |
|---|---|---|---|
| `detection_rate_hz` | float | 10.0 | Target inference frames per second |
| `hfov_deg` | float | 60.0 | Camera horizontal field of view for bearing calculation |
| `publish_annotated_image` | bool | false | Enable annotated image topic (debug only; adds latency) |
| `allow_degraded_startup` | bool | true | Start without model; publish empty results until model loads |

### Detector

| Parameter | Default | Description |
|---|---|---|
| `detector_backend` | `"mock"` | `"mock"` \| `"yolo"` |
| `detector_model_path` | `""` | **Required** when `backend=yolo`. Absolute path to `.pt` file. |
| `detector_confidence` | `0.45` | YOLO confidence threshold |
| `detector_nms_iou` | `0.45` | Non-maximum suppression IoU threshold |
| `detector_device` | `""` | `""` (auto) \| `"cpu"` \| `"cuda:0"` |
| `detector_img_size` | `640` | Input resolution (must be multiple of 32) |
| `detector_timeout_sec` | `1.0` | Per-inference wall-clock deadline |
| `detector_max_timeouts` | `3` | Consecutive timeouts before degraded mode |
| `detector_half` | `false` | FP16 half-precision inference |

### Face pipeline

| Parameter | Default | Description |
|---|---|---|
| `face_detect_backend` | `"mock"` | `"mock"` \| `"opencv_dnn"` \| `"insightface"` |
| `face_recognize_backend` | `"mock"` | `"mock"` \| `"insightface"` \| `"deepface"` |
| `face_db_path` | `""` | Path to identity database (required for recognition) |
| `face_recognition_threshold` | `0.40` | Cosine distance threshold — lower = stricter |
| `face_dnn_prototxt_path` | `""` | `deploy.prototxt` for opencv_dnn detector |
| `face_dnn_weights_path` | `""` | Caffe `.caffemodel` for opencv_dnn detector |
| `face_timeout_sec` | `0.5` | Per-stage face inference deadline |
| `face_min_confidence` | `0.70` | Minimum face detector confidence |

### Preprocessing

| Parameter | Default | Description |
|---|---|---|
| `preprocess_width` | `640` | Resize width before detection |
| `preprocess_height` | `480` | Resize height before detection |
| `preprocess_clahe` | `true` | Enable CLAHE in low-light conditions |
| `preprocess_clahe_clip` | `2.0` | CLAHE clip limit |
| `preprocess_denoise` | `false` | Gaussian denoise before detection |
| `preprocess_brightness_threshold` | `50.0` | Mean brightness below this → CLAHE applied |

### Privacy

| Parameter | Default | Description |
|---|---|---|
| `privacy_enabled` | `false` | Master privacy switch |
| `privacy_blur_faces` | `true` | Blur faces in annotated image |
| `privacy_blur_kernel` | `51` | Gaussian blur kernel size (must be odd ≥ 3) |
| `privacy_pixelate` | `false` | Pixelation instead of Gaussian blur |
| `privacy_suppress_id` | `true` | Omit `face_id` from published `PersonStateArray` |
| `privacy_disable_annotated` | `false` | Completely disable annotated image publishing |

### Tracking

| Parameter | Default | Description |
|---|---|---|
| `tracking_iou_threshold` | `0.30` | Minimum IoU for bbox-to-track assignment |
| `tracking_max_lost` | `15` | Frames before a lost track is deleted |
| `tracking_max_tracks` | `20` | Maximum simultaneous tracked objects |

---

## Backends

### Object detection

| Backend | Dependency | Notes |
|---|---|---|
| `mock` | none | Deterministic synthetic detections — CI / simulation |
| `yolo` | `ultralytics` | YOLOv8/v9/v11 via `pip install ultralytics` |

Model is loaded asynchronously in a background thread during `on_configure()`.  
The node publishes empty results until `ModelState.READY`.

### Face detection

| Backend | Dependency | Notes |
|---|---|---|
| `mock` | none | One synthetic face per frame |
| `opencv_dnn` | `opencv-python` | ResNet-SSD — fast, no GPU required |
| `insightface` | `insightface` | Combined detect + embed (ArcFace) |

### Face recognition

| Backend | Dependency | Notes |
|---|---|---|
| `mock` | none | Always returns empty identity |
| `insightface` | `insightface` | Uses `insightface` detector's embeddings |
| `deepface` | `deepface` | Facenet512 — `pip install deepface` |

---

## Privacy Mode

When `privacy_enabled=true`:

1. All detected face bounding boxes are **blurred or pixelated** in the
   `/bonbon/vision/annotated_image` topic output.  
   The original BGR frame used for inference is **never modified**.

2. `face_id` is set to `""` in every `PersonState` message — even if the
   face was successfully recognised.

3. If `privacy_disable_annotated=true`, the annotated image topic is
   **not published at all**.

> **Critical invariant**: inference accuracy (bounding boxes, depths, class labels)
> is completely unaffected by privacy settings.  Only the *displayed* image and the
> *published identity string* are suppressed.

---

## Quick Start

### Simulation (mock backend, no camera required)

```bash
# Terminal 1 — run with auto-activate
ros2 launch bonbon_vision vision.launch.py

# Terminal 2 — watch detections
ros2 topic echo /bonbon/vision/objects
ros2 topic echo /bonbon/vision/persons
```

### YOLOv8 with USB camera

```bash
# 1. Install dependencies
pip install ultralytics opencv-python

# 2. Download model
wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt

# 3. Launch with real model
ros2 launch bonbon_vision vision.launch.py \
    detector_backend:=yolo \
    model_path:=/absolute/path/to/yolov8n.pt \
    publish_annotated:=true
```

### InsightFace recognition + privacy mode

```bash
pip install insightface deepface

ros2 launch bonbon_vision vision.launch.py \
    face_detect_backend:=insightface \
    face_recognize_backend:=insightface \
    face_db_path:=/opt/bonbon/faces \
    privacy_enabled:=true
```

---

## Testing

```bash
# All unit tests
cd ros2_ws/src/bonbon_vision
python -m pytest tests/ -v

# Specific test file
python -m pytest tests/test_frame_processor.py -v

# Skip ROS2 integration tests (no ROS2 runtime)
python -m pytest tests/ -m "not ros2" -v

# Single scenario
python -m pytest tests/test_detector.py::TestTimeout -v
```

### Test coverage summary

| File | Scenarios |
|---|---|
| `test_frame_processor.py` | OK, low-light, empty, corrupted, wrong shape, resize, depth, config reload |
| `test_frame_throttler.py` | Rate control, burst, drop_rate, stats, thread safety |
| `test_detector.py` | Fake camera, empty/low-light frames, corrupted inference, timeout, degraded mode, depth/bearing fill |
| `test_face_pipeline.py` | Mock backend, privacy mode, detect timeout, recognition timeout, error handling |
| `test_privacy_guard.py` | Original unmodified, blur, pixelation, out-of-bounds bbox, multiple faces, NumPy fallback |
| `test_model_manager.py` | Async load, sync load, wait_ready, failure, degraded flag, reload, thread safety |
| `test_vision_node.py` | Fake camera pipeline, empty/low-light/corrupted frames, tracker, privacy, decode helpers, face fusion |
| `tests/integration/` | Full pipeline wired, config → component, tracker continuity, model lifecycle, privacy pipeline |

---

## Benchmarks

```bash
# Standard benchmark (100 iterations per scenario)
python -m tests.benchmarks.bench_inference

# Quick smoke (20 iterations — for CI)
python -m tests.benchmarks.bench_inference --quick

# Output to JSON
python -m tests.benchmarks.bench_inference --json bench_results.json

# Custom thresholds
python -m tests.benchmarks.bench_inference --iters 500 --min-hz 10.0
```

Typical results on a laptop CPU (Intel Core i7, no GPU):

| Stage | Mean latency |
|---|---|
| FrameProcessor (CLAHE off) | ~0.3 ms |
| FrameProcessor (CLAHE on) | ~1–2 ms |
| MockDetector (2 objects) | ~0.1 ms |
| FacePipeline (mock) | ~0.1 ms |
| PrivacyGuard (blur k=51) | ~2–4 ms |
| End-to-end (mock) | ~3–6 ms |
| FrameThrottler overhead | < 1 µs |

---

## Design Decisions

### Why embed `_SimpleTracker` in `vision_node.py`?

To avoid a circular import dependency with `bonbon_perception` (which has its own
tracker).  The vision node's tracker is minimal — 200 lines — and only needs IoU
assignment + EMA smoothing.

### Why no `cv_bridge`?

`cv_bridge` requires building against the ROS2 C++ bridge, which complicates
simulation setups.  `_decode_color()` and `_decode_depth()` are 5-line static
methods using raw `numpy.frombuffer` — they handle all encodings needed
(`bgr8`, `rgb8`, `32FC1`, `16UC1`) without any C++ dependency.

### Why a `ThreadPoolExecutor` inside `BaseDetector`?

The ROS2 timer callback must return in `< 1/detection_rate_hz` seconds to avoid
timer drift.  Wrapping `_detect_impl()` in a `Future` with `result(timeout=N)`
allows the timer to abandon a hung GPU inference call and re-enter degraded mode
without blocking the entire executor.

### Why not hardcode the model path?

Different deployments use different hardware (Jetson Nano, laptop, cloud GPU).
Model paths differ per-machine and per-environment.  All paths are injected via
ROS2 parameters at launch time.  `DetectorConfig.validate()` emits a clear error
message if you forget to set the path.

---

## Directory Layout

```
bonbon_vision/
├── bonbon_vision/
│   ├── config/
│   │   ├── __init__.py
│   │   ├── vision_config.py        ← Typed nested dataclass config
│   │   └── vision_params.yaml      ← Default parameter YAML
│   ├── preprocessing/
│   │   ├── __init__.py
│   │   ├── frame_processor.py      ← CLAHE, resize, quality gate
│   │   └── frame_throttler.py      ← Token-bucket rate limiter
│   ├── detectors/
│   │   ├── __init__.py
│   │   ├── base_detector.py        ← Timeout + degraded mode (abstract)
│   │   ├── yolo_detector.py        ← YOLOv8 ultralytics backend
│   │   └── mock_detector.py        ← Deterministic test detector
│   ├── face/
│   │   ├── __init__.py
│   │   ├── face_pipeline.py        ← Two-stage detect + recognise
│   │   └── privacy_guard.py        ← Face anonymisation
│   ├── models/
│   │   ├── __init__.py
│   │   └── model_manager.py        ← Async load + ModelState lifecycle
│   └── nodes/
│       ├── __init__.py
│       └── vision_node.py          ← ROS2 LifecycleNode (main entry point)
├── tests/
│   ├── __init__.py
│   ├── test_frame_processor.py
│   ├── test_frame_throttler.py
│   ├── test_detector.py
│   ├── test_face_pipeline.py
│   ├── test_privacy_guard.py
│   ├── test_model_manager.py
│   ├── test_vision_node.py
│   ├── benchmarks/
│   │   ├── __init__.py
│   │   └── bench_inference.py      ← Latency benchmarks
│   └── integration/
│       ├── __init__.py
│       └── test_vision_integration.py
├── launch/
│   └── vision.launch.py
├── resource/
│   └── bonbon_vision
├── package.xml
├── setup.py
├── setup.cfg
└── README.md
```

---

## Dependencies

### Required at runtime

| Package | Purpose |
|---|---|
| `rclpy` | ROS2 Python client library |
| `bonbon_msgs` | Custom message types |
| `numpy` | Array operations |

### Optional (soft imports — graceful fallback if absent)

| Package | Backend | Install |
|---|---|---|
| `opencv-python` | CLAHE, DNN face detector, resize | `pip install opencv-python` |
| `ultralytics` | YOLOv8 detector | `pip install ultralytics` |
| `insightface` | ArcFace detect + recognise | `pip install insightface onnxruntime` |
| `deepface` | Facenet512 recognition | `pip install deepface` |
| `torch` | YOLOv8 inference backend | `pip install torch` |

If any optional package is absent, the corresponding backend falls back to `mock`
and logs a `WARNING`.  The node never crashes on a missing optional dependency.
