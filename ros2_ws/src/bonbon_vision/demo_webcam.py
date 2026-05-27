"""
demo_webcam.py
==============
Standalone demo — NO ROS2 required.

Grabs frames from your webcam (or a video file), runs the full bonbon_vision
pipeline (preprocess → detect → face → track → privacy), and draws results
on screen using OpenCV.

Usage
-----
    # Webcam (default)
    python demo_webcam.py

    # From a video file
    python demo_webcam.py --source path/to/video.mp4

    # Specific webcam index (0, 1, 2 …)
    python demo_webcam.py --source 1

    # Enable privacy mode (blurs detected faces)
    python demo_webcam.py --privacy

Controls
--------
    Q or ESC   — quit
    S          — save a screenshot to demo_screenshot.jpg
    D          — toggle degraded mode (simulate model failure)
    R          — recover from degraded mode
"""

import argparse
import sys
import time
import types


# ── Stub ROS2 so we can import vision_node helpers without a ROS2 install ─────
def _stub(name, **a):
    m = types.ModuleType(name)
    [setattr(m, k, v) for k, v in a.items()]
    return m


try:
    import rclpy  # noqa
except ImportError:
    RP = type("ReliabilityPolicy", (), {"RELIABLE": 1, "BEST_EFFORT": 0})
    DP = type("DurabilityPolicy", (), {"TRANSIENT_LOCAL": 1, "VOLATILE": 0})
    HP = type("HistoryPolicy", (), {"KEEP_LAST": 0})
    LC = type(
        "LifecycleNode",
        (),
        {
            "__init__": lambda s, *a, **k: None,
            "get_logger": lambda s: type(
                "L",
                (),
                {
                    "info": lambda *a: None,
                    "warning": lambda *a: None,
                    "warn": lambda *a: None,
                    "error": lambda *a: None,
                    "debug": lambda *a: None,
                },
            )(),
            "create_timer": lambda *a, **k: None,
            "create_publisher": lambda *a, **k: None,
            "create_subscription": lambda *a, **k: None,
            "declare_parameter": lambda *a, **k: None,
            "get_parameter": lambda s, n: type("P", (), {"value": None})(),
            "get_clock": lambda s: type(
                "C", (), {"now": lambda s: type("N", (), {"to_msg": lambda s: None})()}
            )(),
        },
    )
    TCR = type("TransitionCallbackReturn", (), {"SUCCESS": 0, "ERROR": 1})
    for n, m in {
        "rclpy": _stub("rclpy", init=lambda *a, **k: None, shutdown=lambda: None),
        "rclpy.lifecycle": _stub(
            "rclpy.lifecycle", LifecycleNode=LC, TransitionCallbackReturn=TCR, State=object
        ),
        "rclpy.qos": _stub(
            "rclpy.qos",
            QoSProfile=lambda **kw: None,
            ReliabilityPolicy=RP,
            DurabilityPolicy=DP,
            HistoryPolicy=HP,
        ),
        "geometry_msgs": _stub("geometry_msgs"),
        "geometry_msgs.msg": _stub("geometry_msgs.msg", Point=type("P", (), {})),
        "sensor_msgs": _stub("sensor_msgs"),
        "sensor_msgs.msg": _stub("sensor_msgs.msg", Image=type("I", (), {})),
        "std_msgs": _stub("std_msgs"),
        "std_msgs.msg": _stub("std_msgs.msg", Header=type("H", (), {})),
        "bonbon_msgs": _stub("bonbon_msgs"),
        "bonbon_msgs.msg": _stub(
            "bonbon_msgs.msg",
            DetectedObject=type("DO", (), {}),
            DetectedObjectArray=type("DOA", (), {}),
            ModuleHealth=type("MH", (), {}),
            PersonState=type("PS", (), {}),
            PersonStateArray=type("PSA", (), {}),
        ),
    }.items():
        sys.modules.setdefault(n, m)

import cv2
from bonbon_vision.config.vision_config import (
    FaceConfig,
    PreprocessConfig,
    PrivacyConfig,
)
from bonbon_vision.detectors.mock_detector import MockDetector
from bonbon_vision.face.face_pipeline import FacePipeline
from bonbon_vision.face.privacy_guard import PrivacyGuard
from bonbon_vision.nodes.vision_node import _SimpleTracker
from bonbon_vision.preprocessing.frame_processor import FrameProcessor, FrameQuality
from bonbon_vision.preprocessing.frame_throttler import FrameThrottler

# ── Colour palette for object classes ─────────────────────────────────────────
_COLOURS = [
    (0, 255, 0),  # person  — green
    (255, 140, 0),  # bicycle — orange
    (0, 180, 255),  # car     — blue
    (200, 0, 200),  # chair   — magenta
    (255, 255, 0),  # cup     — yellow
    (100, 255, 100),  # other   — light green
]


def _colour(class_id: int):
    return _COLOURS[class_id % len(_COLOURS)]


def _draw_detections(frame, tracks, face_bboxes, quality, stats):
    """Annotate frame in-place with track boxes, labels, and HUD."""
    h, w = frame.shape[:2]

    # Draw each confirmed track
    for t in tracks:
        x, y, bw, bh = [int(v) for v in t.bbox]
        col = (0, 220, 0)  # green for confirmed
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), col, 2)

        label = t.track_id
        if hasattr(t, "face_id") and t.face_id:
            label += f"  [{t.face_id}]"

        depth = t.distance_m
        if hasattr(depth, "__float__") and depth == depth:  # not NaN
            label += f"  {depth:.1f}m"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x, y - th - 8), (x + tw + 4, y), col, -1)
        cv2.putText(
            frame, label, (x + 2, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA
        )

    # Draw face bboxes
    for fx, fy, fw, fh in face_bboxes:
        cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (180, 0, 255), 1)

    # HUD
    lines = [
        f"Tracks: {len(tracks)}   Quality: {quality.name}",
        f"FPS: {stats['fps']:.1f}   Frame: {stats['frame']}",
        f"Degraded: {stats['degraded']}   Press D=degrade R=recover Q=quit S=screenshot",
    ]
    for i, line in enumerate(lines):
        y_pos = 20 + i * 22
        cv2.rectangle(frame, (0, y_pos - 16), (w, y_pos + 4), (0, 0, 0), -1)
        cv2.putText(
            frame, line, (6, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA
        )


def main():
    parser = argparse.ArgumentParser(description="bonbon_vision standalone demo")
    parser.add_argument("--source", default="0", help="Webcam index (0,1,2…) or path to video file")
    parser.add_argument(
        "--privacy", action="store_true", help="Enable privacy mode (blur faces in display)"
    )
    parser.add_argument(
        "--rate", type=float, default=10.0, help="Target detection rate Hz (default 10)"
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    # Try to parse source as integer (webcam index)
    try:
        source = int(args.source)
    except ValueError:
        source = args.source

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"ERROR: Cannot open camera/video source: {source!r}")
        print("  → Try a different index: --source 1")
        print("  → Or point to a video file: --source path/to/video.mp4")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    print("\n[bonbon_vision demo]")
    print(f"  Source  : {source}")
    print(f"  Privacy : {args.privacy}")
    print(f"  Rate    : {args.rate} Hz")
    print("  Controls: Q=quit  S=screenshot  D=degrade  R=recover\n")

    # ── Build pipeline ────────────────────────────────────────────────────────

    pre_cfg = PreprocessConfig(
        resize_width=args.width,
        resize_height=args.height,
        enable_clahe=True,
        brightness_threshold=50.0,
        min_mean_brightness=2.0,
    )
    processor = FrameProcessor(pre_cfg)
    throttler = FrameThrottler(target_hz=args.rate)
    detector = MockDetector(num_detections=3, randomise=True)  # synthetic objects
    face_pipe = FacePipeline(
        FaceConfig(detect_backend="mock", recognize_backend="mock"),
        privacy_mode=args.privacy,
    )
    privacy = PrivacyGuard(
        PrivacyConfig(
            enabled=args.privacy,
            blur_kernel_size=31,
        )
    )
    tracker = _SimpleTracker(iou_thresh=0.3, max_lost=15, max_tracks=20)

    # ── Loop ─────────────────────────────────────────────────────────────────

    frame_count = 0
    fps_t0 = time.monotonic()
    fps = 0.0

    while True:
        ret, bgr = cap.read()
        if not ret:
            print("  End of stream or read error — stopping.")
            break

        frame_count += 1
        elapsed = time.monotonic() - fps_t0
        if elapsed >= 1.0:
            fps = frame_count / elapsed
            fps_t0 = time.monotonic()
            frame_count = 0

        annotated = bgr.copy()  # display copy — inference frame is never modified

        quality = FrameQuality.OK
        tracks = []
        face_bbs = []

        if throttler.should_process():
            pf = processor.process(bgr)
            quality = pf.quality

            if pf.is_usable:
                det_r = detector.detect(pf.bgr)
                face_r = face_pipe.run(pf.bgr)

                # Scale bboxes back to display size (processor resizes to pre_cfg dims)
                # In this demo pre_cfg matches capture size so no scaling needed.
                tracks = tracker.update(det_r.detections)
                face_bbs = [f.bbox for f in face_r.faces]

                # Apply privacy guard to the display copy only
                annotated = privacy.anonymise(annotated, face_bbs)

        _draw_detections(
            annotated,
            tracks,
            face_bbs,
            quality,
            stats={
                "fps": fps,
                "frame": detector.call_count,
                "degraded": detector.is_degraded,
            },
        )

        cv2.imshow("bonbon_vision demo  (Q=quit)", annotated)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):  # Q or ESC
            break
        elif key == ord("s"):
            fname = "demo_screenshot.jpg"
            cv2.imwrite(fname, annotated)
            print(f"  Screenshot saved: {fname}")
        elif key == ord("d"):
            detector.force_degraded("demo_key_D")
            print("  Detector → DEGRADED (press R to recover)")
        elif key == ord("r"):
            detector.recover()
            print("  Detector → RECOVERED")

    cap.release()
    cv2.destroyAllWindows()
    detector.shutdown()
    face_pipe.shutdown()
    print("\nDemo ended.")


if __name__ == "__main__":
    main()
