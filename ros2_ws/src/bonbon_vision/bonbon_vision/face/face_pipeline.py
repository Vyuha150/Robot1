"""
bonbon_vision.face.face_pipeline
==================================
Combined face detection + recognition pipeline with timeout handling.

Two-stage process
-----------------
Stage 1 — Face detection
    Locates face bounding boxes in the BGR frame.
    Backends: "opencv_dnn" | "insightface" | "mock"

Stage 2 — Face recognition
    Embeds each detected face and matches against the enrolled database.
    Backends: "deepface" | "insightface" | "mock"

Timeout
-------
Both stages are submitted to a shared ThreadPoolExecutor with an
individual deadline.  On timeout the pipeline returns whatever partial
results are available (stage 1 results kept, stage 2 skipped if it
times out independently).

Database path
-------------
Never hardcoded.  Injected via FaceConfig.db_path from the ROS2
parameter 'face_db_path'.

Structured log format
---------------------
    logger.debug("stage=%s n_faces=%d inference_ms=%.1f", …)
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field

import numpy as np

from ..config.vision_config import FaceConfig

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class FaceDetection:
    """A single detected + (optionally) recognised face."""

    bbox: tuple[int, int, int, int]  # (x, y, w, h) in image pixels
    confidence: float  # detector confidence
    face_id: str = ""  # "" = unknown / not in DB
    age_group: str = "unknown"  # "child"|"adult"|"elderly"|"unknown"
    facing_robot: bool = False  # body-pose gaze estimation


@dataclass
class FaceResult:
    """Output of one FacePipeline.run() call."""

    faces: list[FaceDetection] = field(default_factory=list)
    detect_ms: float = 0.0
    recognize_ms: float = 0.0
    detect_timed_out: bool = False
    recognize_timed_out: bool = False
    error: str | None = None


# ── Mock implementations ──────────────────────────────────────────────────────


class _MockFaceDetector:
    """Returns one synthetic face centred on the nearest YOLO person bbox."""

    def detect(self, bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
        h, w = bgr.shape[:2]
        face_w = max(40, w // 8)
        face_h = int(face_w * 1.2)
        cx, cy = w // 2, int(h * 0.3)
        return [(cx - face_w // 2, cy - face_h // 2, face_w, face_h)]


class _MockFaceRecognizer:
    _DB = {"person_0": "Alice", "person_1": "Bob", "person_2": "Carol"}

    def identify(self, face_crop: np.ndarray, db_path: str, threshold: float) -> str:
        return ""  # no track_id here; VisionNode maps by geometry


# ── OpenCV DNN face detector ─────────────────────────────────────────────────


class _OpenCVDNNFaceDetector:
    """
    OpenCV DNN face detector (ResNet-SSD, Caffe model).
    Requires:
      prototxt: deploy.prototxt from opencv_face_detector
      weights:  opencv_face_detector_uint8.caffemodel
    """

    def __init__(self, prototxt: str, weights: str, min_confidence: float = 0.70) -> None:
        try:
            import cv2

            self._net = cv2.dnn.readNetFromCaffe(prototxt, weights)
            self._min_conf = min_confidence
            self._cv2 = cv2
        except Exception as exc:
            raise ImportError(f"OpenCV DNN face detector failed to load: {exc}") from exc

    def detect(self, bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
        h, w = bgr.shape[:2]
        blob = self._cv2.dnn.blobFromImage(
            self._cv2.resize(bgr, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0)
        )
        self._net.setInput(blob)
        detections = self._net.forward()
        faces = []
        for i in range(detections.shape[2]):
            conf = float(detections[0, 0, i, 2])
            if conf < self._min_conf:
                continue
            x1 = int(detections[0, 0, i, 3] * w)
            y1 = int(detections[0, 0, i, 4] * h)
            x2 = int(detections[0, 0, i, 5] * w)
            y2 = int(detections[0, 0, i, 6] * h)
            faces.append(
                (
                    max(0, x1),
                    max(0, y1),
                    min(w, x2) - max(0, x1),
                    min(h, y2) - max(0, y1),
                )
            )
        return faces


# ── InsightFace pipeline ──────────────────────────────────────────────────────


class _InsightFacePipeline:
    """InsightFace (ArcFace) — combined detect + recognize."""

    def __init__(self, db_path: str, threshold: float = 0.40) -> None:
        try:
            import insightface  # noqa: F401
            from insightface.app import FaceAnalysis

            self._app = FaceAnalysis(providers=["CPUExecutionProvider"])
            self._app.prepare(ctx_id=0, det_size=(640, 640))
            self._db_path = db_path
            self._threshold = threshold
            self._embeddings = self._load_db()
        except ImportError:
            raise ImportError("insightface not installed. Run: pip install insightface") from None

    def _load_db(self):
        import os
        import pickle

        db_file = os.path.join(self._db_path, "embeddings.pkl")
        if os.path.exists(db_file):
            with open(db_file, "rb") as fh:
                return pickle.load(fh)
        return {}

    def run(self, bgr: np.ndarray) -> list[FaceDetection]:
        faces = self._app.get(bgr)
        results = []
        for face in faces:
            bbox = face.bbox.astype(int)
            x1, y1, x2, y2 = bbox
            face_id = self._match_embedding(face.embedding)
            results.append(
                FaceDetection(
                    bbox=(x1, y1, x2 - x1, y2 - y1),
                    confidence=float(face.det_score),
                    face_id=face_id,
                )
            )
        return results

    def _match_embedding(self, emb: np.ndarray) -> str:
        best_name, best_dist = "", float("inf")
        for name, db_emb in self._embeddings.items():
            dist = float(np.linalg.norm(emb - db_emb))
            if dist < best_dist:
                best_dist, best_name = dist, name
        if best_dist < self._threshold:
            return best_name
        return ""


# ── DeepFace recognizer ───────────────────────────────────────────────────────


class _DeepFaceRecognizer:
    def __init__(self, db_path: str, threshold: float = 0.40) -> None:
        try:
            from deepface import DeepFace

            self._DF = DeepFace
            self._db_path = db_path
            self._threshold = threshold
        except ImportError:
            raise ImportError("deepface not installed. Run: pip install deepface") from None

    def identify(self, face_crop: np.ndarray, _db: str, _thresh: float) -> str:
        if not self._db_path:
            return ""
        try:
            result = self._DF.find(
                img_path=face_crop,
                db_path=self._db_path,
                model_name="Facenet512",
                enforce_detection=False,
                silent=True,
            )
            if result and len(result[0]) > 0:
                row = result[0].iloc[0]
                dist = row.get("Facenet512_cosine", float("inf"))
                if dist < self._threshold:
                    import os

                    return os.path.splitext(os.path.basename(str(row["identity"])))[0]
        except Exception:
            pass
        return ""


# ── Pipeline ──────────────────────────────────────────────────────────────────


class FacePipeline:
    """
    Orchestrates face detection → recognition → result building.

    Parameters
    ----------
    cfg          FaceConfig   typed configuration
    privacy_mode bool         if True, face_id is always suppressed ("")
    """

    def __init__(self, cfg: FaceConfig, privacy_mode: bool = False) -> None:
        self._cfg = cfg
        self._privacy_mode = privacy_mode
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face_pipeline")
        self._detector = None
        self._recognizer = None
        self._insightface = None
        self._load_backends()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _load_backends(self) -> None:
        """Load detection and recognition backends; fall back to mock on error."""
        det_b = self._cfg.detect_backend
        recog_b = self._cfg.recognize_backend

        # Detection backend
        if det_b == "mock":
            self._detector = _MockFaceDetector()
        elif det_b == "opencv_dnn":
            try:
                self._detector = _OpenCVDNNFaceDetector(
                    self._cfg.dnn_prototxt_path,
                    self._cfg.dnn_weights_path,
                    self._cfg.min_face_confidence,
                )
            except Exception as exc:
                logger.warning(
                    "stage=face_load backend=opencv_dnn error=%r " "fallback=mock", str(exc)
                )
                self._detector = _MockFaceDetector()
        elif det_b == "insightface":
            try:
                self._insightface = _InsightFacePipeline(
                    self._cfg.db_path,
                    self._cfg.recognition_threshold,
                )
            except Exception as exc:
                logger.warning(
                    "stage=face_load backend=insightface error=%r " "fallback=mock", str(exc)
                )
                self._detector = _MockFaceDetector()
        else:
            logger.warning("stage=face_load backend=%r unknown fallback=mock", det_b)
            self._detector = _MockFaceDetector()

        # Recognition backend (skip when insightface handles both)
        if self._insightface is None:
            if recog_b == "mock":
                self._recognizer = _MockFaceRecognizer()
            elif recog_b == "deepface":
                try:
                    self._recognizer = _DeepFaceRecognizer(
                        self._cfg.db_path,
                        self._cfg.recognition_threshold,
                    )
                except Exception as exc:
                    logger.warning(
                        "stage=face_load recog=deepface error=%r " "fallback=mock", str(exc)
                    )
                    self._recognizer = _MockFaceRecognizer()
            else:
                self._recognizer = _MockFaceRecognizer()

        logger.info(
            "stage=face_load detect_backend=%r recognize_backend=%r " "privacy_mode=%s",
            det_b,
            recog_b,
            self._privacy_mode,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, bgr: np.ndarray) -> FaceResult:
        """
        Detect and optionally recognise faces in a BGR image.
        Returns FaceResult with timing and per-face data.
        """
        result = FaceResult()

        # InsightFace: combined detect + recognize in one call
        if self._insightface is not None:
            t0 = time.monotonic()
            try:
                timeout = self._cfg.inference_timeout_sec
                future = self._executor.submit(self._insightface.run, bgr)
                faces = future.result(timeout=timeout)
                result.faces = self._apply_privacy(faces)
                result.detect_ms = (time.monotonic() - t0) * 1000
                result.recognize_ms = 0.0
            except FuturesTimeout:
                result.detect_timed_out = True
                result.recognize_timed_out = True
                logger.warning("stage=face event=timeout backend=insightface")
            except Exception as exc:
                result.error = str(exc)
                logger.error("stage=face event=error error=%r", str(exc))
            return result

        # Stage 1: face detection
        t0 = time.monotonic()
        try:
            timeout = self._cfg.inference_timeout_sec
            future = self._executor.submit(self._detector.detect, bgr)
            bboxes = future.result(timeout=timeout)
            result.detect_ms = (time.monotonic() - t0) * 1000
        except FuturesTimeout:
            result.detect_timed_out = True
            logger.warning("stage=face_detect event=timeout")
            return result
        except Exception as exc:
            result.error = str(exc)
            logger.error("stage=face_detect event=error error=%r", str(exc))
            return result

        logger.debug(
            "stage=face_detect n_faces=%d detect_ms=%.1f",
            len(bboxes),
            result.detect_ms,
        )

        # Stage 2: recognition
        faces: list[FaceDetection] = []
        h, w = bgr.shape[:2]
        t1 = time.monotonic()
        for bbox in bboxes:
            x, y, bw, bh = bbox
            x = max(0, x)
            y = max(0, y)
            bw = min(w - x, bw)
            bh = min(h - y, bh)
            crop = bgr[y : y + bh, x : x + bw]
            face_id = ""
            if crop.size > 0 and not self._privacy_mode:
                try:
                    future = self._executor.submit(
                        self._recognizer.identify,
                        crop,
                        self._cfg.db_path,
                        self._cfg.recognition_threshold,
                    )
                    face_id = future.result(timeout=self._cfg.inference_timeout_sec)
                except FuturesTimeout:
                    result.recognize_timed_out = True
                except Exception:
                    pass
            faces.append(FaceDetection(bbox=bbox, confidence=1.0, face_id=face_id))

        result.recognize_ms = (time.monotonic() - t1) * 1000
        result.faces = self._apply_privacy(faces)

        logger.debug(
            "stage=face_recognize n_recognized=%d recognize_ms=%.1f",
            sum(1 for f in result.faces if f.face_id),
            result.recognize_ms,
        )
        return result

    def _apply_privacy(self, faces: list) -> list:
        if self._privacy_mode:
            for f in faces:
                f.face_id = ""
        return faces

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
