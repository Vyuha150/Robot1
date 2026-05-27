"""
bonbon_perception.detectors.yolo_person_detector
=================================================
Real person detector using YOLOv8 (ultralytics) or YOLOv5 (torch hub).

Detection speed on Jetson Orin Nano (with TensorRT export)
----------------------------------------------------------
  YOLOv8n-TRT  640×480  ~30 Hz
  YOLOv8s-TRT  640×480  ~20 Hz
  YOLOv8n-PT   640×480  ~12 Hz (PyTorch, no TRT)

Recommended model: yolov8n.pt (Nano) — 3.2 MB, good accuracy at service
robot range (0.5–5 m).

Usage
-----
  from bonbon_perception.detectors import YoloPersonDetector

  det = YoloPersonDetector(model_path="yolov8n.pt")
  detections = det.detect(color_bgr, depth_m)

Requires: pip install ultralytics  (or pip install torch torchvision yolov5)
"""

from __future__ import annotations

import numpy as np

# Soft import — allows the module to load even without ultralytics
try:
    from ultralytics import YOLO as _YOLO

    _HAS_ULTRALYTICS = True
except ImportError:
    _HAS_ULTRALYTICS = False

try:
    import torch as _torch

    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

from .person_detector import Detection, PersonDetector

# COCO class index for "person"
_COCO_PERSON = 0


class YoloPersonDetector(PersonDetector):
    """
    YOLO-based person detector supporting both ultralytics (YOLOv8) and
    torch.hub (YOLOv5) backends.

    Parameters
    ----------
    model_path       str / Path  path to model weights (.pt) or model name
    device           str         "cpu", "cuda:0", "mps", or "" (auto-detect)
    img_size         int         inference resolution (input long-side)
    half             bool        use FP16 inference (requires CUDA)
    backend          str         "ultralytics" | "torchub" | "auto"
    """

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.45,
        hfov_deg: float = 60.0,
        device: str = "",
        img_size: int = 640,
        half: bool = False,
        backend: str = "auto",
    ) -> None:
        super().__init__(
            confidence_threshold=confidence_threshold,
            hfov_deg=hfov_deg,
        )
        self._model_path = str(model_path)
        self._device = device
        self._img_size = img_size
        self._half = half
        self._backend = backend
        self._model = None

        self._load_model()

    # ── Model loading ─────────────────────────────────────────────────────────

    def _load_model(self) -> None:
        if self._backend == "auto":
            if _HAS_ULTRALYTICS:
                self._backend = "ultralytics"
            elif _HAS_TORCH:
                self._backend = "torchhub"
            else:
                raise ImportError(
                    "YoloPersonDetector requires either ultralytics or torch. "
                    "Install with: pip install ultralytics"
                )

        if self._backend == "ultralytics":
            if not _HAS_ULTRALYTICS:
                raise ImportError("ultralytics not installed. Run: pip install ultralytics")
            self._model = _YOLO(self._model_path)
            # Warm up
            dummy = np.zeros((480, 640, 3), dtype=np.uint8)
            self._model(dummy, verbose=False)

        elif self._backend == "torchhub":
            if not _HAS_TORCH:
                raise ImportError("torch not installed. Run: pip install torch torchvision")
            self._model = _torch.hub.load(
                "ultralytics/yolov5",
                "custom",
                path=self._model_path,
                verbose=False,
            )
            self._model.conf = self.confidence_threshold
            if self._device:
                self._model.to(self._device)
        else:
            raise ValueError(f"Unknown YOLO backend: {self._backend!r}")

    # ── Core implementation ───────────────────────────────────────────────────

    def _detect_impl(self, color_bgr: np.ndarray) -> list[Detection]:
        if self._model is None:
            return []

        if self._backend == "ultralytics":
            return self._detect_ultralytics(color_bgr)
        else:
            return self._detect_torchhub(color_bgr)

    def _detect_ultralytics(self, color_bgr: np.ndarray) -> list[Detection]:
        results = self._model(
            color_bgr,
            classes=[_COCO_PERSON],
            conf=self.confidence_threshold,
            imgsz=self._img_size,
            verbose=False,
            half=self._half,
        )
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls = int(box.cls[0])
                if cls != _COCO_PERSON:
                    continue
                conf = float(box.conf[0])
                xyxy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = xyxy
                det = Detection(
                    bbox=(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                    confidence=conf,
                )
                detections.append(det)
        return sorted(detections, key=lambda d: d.confidence, reverse=True)

    def _detect_torchhub(self, color_bgr: np.ndarray) -> list[Detection]:
        import cv2

        rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)
        results = self._model(rgb)
        detections: list[Detection] = []
        for *xyxy, conf, cls in results.xyxy[0].cpu().numpy():
            if int(cls) != _COCO_PERSON:
                continue
            if float(conf) < self.confidence_threshold:
                continue
            x1, y1, x2, y2 = map(int, xyxy)
            det = Detection(
                bbox=(x1, y1, x2 - x1, y2 - y1),
                confidence=float(conf),
            )
            detections.append(det)
        return sorted(detections, key=lambda d: d.confidence, reverse=True)
