"""
bonbon_perception.nodes.face_node
===================================
CLASS-D AUXILIARY: Face recognition node.

Subscribes (from detection_node + HAL camera_node)
---------------------------------------------------
  /bonbon/vision/persons                  bonbon_msgs/PersonStateArray
  /bonbon/vision/camera/color/image_raw   sensor_msgs/Image   BGR8

Publishes
---------
  /bonbon/vision/persons_identified       bonbon_msgs/PersonStateArray
      Same structure as /bonbon/vision/persons but with face_id populated
      for recognized individuals.
  /bonbon/vision/face_node/health         bonbon_msgs/ModuleHealth       1 Hz

Database
--------
  Face embeddings are stored in a simple SQLite database:
    /var/lib/bonbon/face_db.sqlite  (configurable via face_db_path param)
  Each registered person has:
    name TEXT  — display name / patient ID
    embedding BLOB  — 128-dim float32 L2-normalized face embedding

  The node exposes a ROS2 service:
    /bonbon/face/register   (bonbon_srvs/FaceRegister — not yet defined)
  If bonbon_srvs does not define FaceRegister the service is skipped.

Detector backend
----------------
  "mock"        — assigns face IDs deterministically by track_id (CI safe)
  "opencv_lbp"  — OpenCV LBP face detector + EigenFaces recognizer
  "deepface"    — DeepFace (Facenet512) embeddings + cosine distance
  "insightface" — InsightFace ArcFace (highest accuracy, GPU preferred)

Parameters
----------
  face_mode          str    "mock"|"opencv_lbp"|"deepface"|"insightface"
  face_db_path       str    path to face embedding database
  recognition_threshold float cosine distance threshold (0=identical)
  health_rate_hz     float  default 1.0
  crop_scale         float  scale bbox for face crop (default 1.3)
"""

from __future__ import annotations

import sqlite3
import threading
import time

import numpy as np
import rclpy
from bonbon_msgs.msg import (
    ModuleHealth,
)
from bonbon_msgs.msg import (
    PersonState as PersonStateMsg,
)
from bonbon_msgs.msg import (
    PersonStateArray as PersonStateArrayMsg,
)
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

# ── QoS profiles ──────────────────────────────────────────────────────────────

RELIABLE_TL = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
RELIABLE_D5 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)
BEST_EFFORT_D2 = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=2,
)

NODE_NAME = "face_node"
HEALTH_TOPIC = "/bonbon/vision/face_node/health"

# ── Fake face database (mock mode) ───────────────────────────────────────────

_MOCK_FACES: dict[str, str] = {
    "person_0": "Alice",
    "person_1": "Bob",
    "person_2": "Carol",
}


# ── Node ──────────────────────────────────────────────────────────────────────


class FaceNode(LifecycleNode):
    """
    Face recognition node — augments PersonStateArray with registered identities.
    """

    def __init__(self) -> None:
        super().__init__(NODE_NAME)
        self._lock = threading.Lock()

        self._latest_color: np.ndarray | None = None
        self._face_engine = None
        self._db_conn: sqlite3.Connection | None = None

        self._pub_identified = None
        self._pub_health = None
        self._health_timer = None

        self._start_time = time.monotonic()
        self._processed_count: int = 0
        self._error_count: int = 0
        self._warning_count: int = 0
        self._last_latency_ms: float = 0.0

        self._declare_parameters()
        self.get_logger().info(f"[{NODE_NAME}] created")

    # ── Parameters ────────────────────────────────────────────────────────────

    def _declare_parameters(self) -> None:
        self.declare_parameter("face_mode", "mock")
        self.declare_parameter("face_db_path", "/var/lib/bonbon/face_db.sqlite")
        self.declare_parameter("recognition_threshold", 0.4)
        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("crop_scale", 1.3)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Configuring…")
        try:
            mode = self.get_parameter("face_mode").value
            self._recognition_threshold = self.get_parameter("recognition_threshold").value
            self._crop_scale = float(self.get_parameter("crop_scale").value)
            self._face_engine = self._make_face_engine(mode)
        except Exception as exc:
            self.get_logger().error(f"[{NODE_NAME}] Configure failed: {exc}")
            return TransitionCallbackReturn.FAILURE

        self.get_logger().info(
            f"[{NODE_NAME}] Configured — face_mode={self.get_parameter('face_mode').value}"
        )
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Activating…")

        self._pub_identified = self.create_lifecycle_publisher(
            PersonStateArrayMsg,
            "/bonbon/vision/persons_identified",
            RELIABLE_D5,
        )
        self._pub_health = self.create_lifecycle_publisher(ModuleHealth, HEALTH_TOPIC, RELIABLE_TL)

        self._sub_persons = self.create_subscription(
            PersonStateArrayMsg,
            "/bonbon/vision/persons",
            self._on_persons,
            RELIABLE_D5,
        )
        self._sub_color = self.create_subscription(
            Image,
            "/bonbon/vision/camera/color/image_raw",
            self._on_color_image,
            BEST_EFFORT_D2,
        )

        health_period = 1.0 / max(0.1, self.get_parameter("health_rate_hz").value)
        self._health_timer = self.create_timer(health_period, self._publish_health)

        self.get_logger().info(f"[{NODE_NAME}] Active")
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        if self._health_timer:
            self._health_timer.cancel()
            self._health_timer = None
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None
        self._pub_identified = None
        self._pub_health = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        if self._db_conn:
            self._db_conn.close()
        return TransitionCallbackReturn.SUCCESS

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_color_image(self, msg: Image) -> None:
        try:
            h, w = msg.height, msg.width
            arr = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, -1))
            with self._lock:
                self._latest_color = arr.copy()
        except Exception as exc:
            self._error_count += 1
            self.get_logger().debug(f"[{NODE_NAME}] Image decode error: {exc}")

    def _on_persons(self, msg: PersonStateArrayMsg) -> None:
        if not msg.persons:
            if self._pub_identified:
                self._pub_identified.publish(msg)
            return

        with self._lock:
            color = self._latest_color

        t0 = time.monotonic()
        try:
            identified = self._run_recognition(msg, color)
        except Exception as exc:
            self._error_count += 1
            self.get_logger().warn(f"[{NODE_NAME}] Recognition error: {exc}")
            if self._pub_identified:
                self._pub_identified.publish(msg)  # pass through unchanged
            return

        self._last_latency_ms = (time.monotonic() - t0) * 1000.0
        self._processed_count += 1

        if self._pub_identified:
            self._pub_identified.publish(identified)

    # ── Recognition ──────────────────────────────────────────────────────────

    def _run_recognition(
        self,
        msg: PersonStateArrayMsg,
        color: np.ndarray | None,
    ) -> PersonStateArrayMsg:
        """Run face recognition on each person in the array."""
        out = PersonStateArrayMsg()
        out.header = msg.header
        out.total_count = msg.total_count

        for person in msg.persons:
            augmented = PersonStateMsg()
            augmented.track_id = person.track_id
            augmented.face_id = person.face_id
            augmented.distance_m = person.distance_m
            augmented.bearing_deg = person.bearing_deg
            augmented.velocity_mps = person.velocity_mps
            augmented.facing_robot = person.facing_robot
            augmented.age_group = person.age_group
            augmented.position = person.position

            face_id = self._face_engine.identify(person, color, self._recognition_threshold)
            if face_id:
                augmented.face_id = face_id
            out.persons.append(augmented)

        return out

    # ── Face engine factory ───────────────────────────────────────────────────

    def _make_face_engine(self, mode: str):
        if mode == "mock":
            return _MockFaceEngine()
        elif mode == "opencv_lbp":
            try:
                return _OpenCVLBPFaceEngine(db_path=self.get_parameter("face_db_path").value)
            except Exception as exc:
                self.get_logger().warn(
                    f"[{NODE_NAME}] OpenCV LBP face engine failed: {exc} — using mock"
                )
                return _MockFaceEngine()
        elif mode == "deepface":
            try:
                return _DeepFaceEngine(db_path=self.get_parameter("face_db_path").value)
            except Exception as exc:
                self.get_logger().warn(f"[{NODE_NAME}] DeepFace engine failed: {exc} — using mock")
                return _MockFaceEngine()
        else:
            self.get_logger().warn(f"[{NODE_NAME}] Unknown face_mode '{mode}' — using mock")
            return _MockFaceEngine()

    # ── Health ────────────────────────────────────────────────────────────────

    def _publish_health(self) -> None:
        if self._pub_health is None:
            return
        uptime = time.monotonic() - self._start_time

        status = ModuleHealth.ERROR if self._error_count > 5 else ModuleHealth.OK
        status_txt = (
            f"Face recognition active. Processed {self._processed_count} frames. "
            f"Latency {self._last_latency_ms:.1f} ms"
        )

        msg = ModuleHealth()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.module_name = NODE_NAME
        msg.status = status
        msg.status_text = status_txt
        msg.uptime_sec = uptime
        msg.last_successful_cycle_sec = 0.0
        msg.latency_ms = self._last_latency_ms
        msg.error_count = self._error_count
        msg.warning_count = self._warning_count
        msg.processed_count = self._processed_count
        self._pub_health.publish(msg)


# ── Face engine implementations ───────────────────────────────────────────────


class _MockFaceEngine:
    """Deterministic face engine for CI and simulation."""

    def identify(self, person, color, threshold: float) -> str:
        return _MOCK_FACES.get(person.track_id, "")


class _OpenCVLBPFaceEngine:
    """OpenCV Local Binary Pattern face detector + Eigenfaces recognizer."""

    def __init__(self, db_path: str) -> None:
        try:
            import cv2

            self._cv2 = cv2
            self._detector = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            self._recognizer = cv2.face.LBPHFaceRecognizer_create()
            self._db_path = db_path
            self._label_map: dict[int, str] = {}
            self._trained = False
            self._load_db()
        except ImportError:
            raise ImportError(
                "OpenCV with face module required: pip install opencv-contrib-python"
            ) from None

    def _load_db(self) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT name, embedding FROM face_embeddings")
            rows = c.fetchall()
            conn.close()
            if rows:
                labels = []
                images = []
                for i, (name, blob) in enumerate(rows):
                    self._label_map[i] = name
                    emb = np.frombuffer(blob, dtype=np.float32).reshape(64, -1)
                    images.append(emb.astype(np.uint8))
                    labels.append(i)
                self._recognizer.train(images, np.array(labels))
                self._trained = True
        except Exception:
            pass  # empty or missing DB — recognition simply returns ""

    def identify(self, person, color, threshold: float) -> str:
        if color is None or not self._trained:
            return ""
        try:
            gray = self._cv2.cvtColor(color, self._cv2.COLOR_BGR2GRAY)
            faces = self._detector.detectMultiScale(gray, 1.1, 5)
            if len(faces) == 0:
                return ""
            x, y, w, h = faces[0]
            face_roi = self._cv2.resize(gray[y : y + h, x : x + w], (64, 64))
            label, confidence = self._recognizer.predict(face_roi)
            if confidence < threshold * 100:
                return self._label_map.get(label, "")
        except Exception:
            pass
        return ""


class _DeepFaceEngine:
    """DeepFace (Facenet512) face recognition."""

    def __init__(self, db_path: str) -> None:
        try:
            from deepface import DeepFace as _DF

            self._DF = _DF
            self._db_path = db_path
        except ImportError:
            raise ImportError("DeepFace not installed. Run: pip install deepface") from None

    def identify(self, person, color, threshold: float) -> str:
        if color is None:
            return ""
        try:
            import cv2

            rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
            result = self._DF.find(
                img_path=rgb,
                db_path=self._db_path,
                model_name="Facenet512",
                enforce_detection=False,
                silent=True,
            )
            if result and len(result[0]) > 0:
                row = result[0].iloc[0]
                if row["Facenet512_cosine"] < threshold:
                    import os

                    return os.path.splitext(os.path.basename(str(row["identity"])))[0]
        except Exception:
            pass
        return ""


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> None:
    rclpy.init(args=args)
    node = FaceNode()
    executor = rclpy.executors.MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
