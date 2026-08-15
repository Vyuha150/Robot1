"""
bonbon_perception.detectors.mock_person_detector
=================================================
Simulation-safe person detector for CI and hardware-free testing.

Behaviour
---------
  * Returns a configurable number of synthetic persons placed in a deterministic
    pattern across the image.
  * Supports scripted scenarios: inject a person at a specific pixel coordinate
    or at a specific distance.
  * Supports fault injection: skip N detections, return zero persons, or
    raise an exception to test error-handling paths.

All injected persons are valid Detection objects with plausible bounding boxes,
confidence values, depth readings, and bearing angles so downstream code
(tracker, node) never sees unrealistic data.
"""

from __future__ import annotations

import numpy as np

from .person_detector import Detection, PersonDetector


class MockPersonDetector(PersonDetector):
    """
    Synthetic person detector for simulation and testing.

    Constructor parameters
    ----------------------
    num_persons          int   0–8     number of persons to generate per frame
    base_distance_m      float         distance of the nearest synthesised person
    distance_step_m      float         additional distance per extra person
    confidence           float         fixed confidence for all detections
    image_width          int           assumed image width for bearing calc
    image_height         int           assumed image height for bbox sizing
    skip_every_n         int   0       if >0, every N-th call returns []
    fail_on_call         int   -1      if >=0, raises RuntimeError on that call
    inject_person        dict  None    one-shot: inject a person at specific coords
    """

    def __init__(
        self,
        num_persons: int = 1,
        base_distance_m: float = 2.0,
        distance_step_m: float = 0.8,
        confidence: float = 0.92,
        image_width: int = 640,
        image_height: int = 480,
        hfov_deg: float = 60.0,
        skip_every_n: int = 0,
        fail_on_call: int = -1,
        inject_person: dict | None = None,
    ) -> None:
        super().__init__(confidence_threshold=0.5, hfov_deg=hfov_deg)
        self._num_persons = num_persons
        self._base_distance = base_distance_m
        self._distance_step = distance_step_m
        self._confidence = confidence
        self._img_w = image_width
        self._img_h = image_height
        self._skip_every_n = skip_every_n
        self._fail_on_call = fail_on_call
        self._inject_person = inject_person
        self._call_count: int = 0
        self._injected_once = False

    # ── Core implementation ───────────────────────────────────────────────────

    def _detect_impl(self, color_bgr: np.ndarray) -> list[Detection]:
        self._call_count += 1

        # Fault: raise on specific call
        if self._fail_on_call >= 0 and self._call_count == self._fail_on_call:
            raise RuntimeError(f"MockPersonDetector: simulated failure on call {self._call_count}")

        # Fault: skip (return empty) every N calls
        if self._skip_every_n > 0 and self._call_count % self._skip_every_n == 0:
            return []

        h, w = color_bgr.shape[:2]
        detections: list[Detection] = []

        # One-shot injected person
        if self._inject_person and not self._injected_once:
            det = self._make_injected(self._inject_person, w, h)
            if det is not None:
                detections.append(det)
            self._injected_once = True

        # Regular synthetic persons
        for i in range(self._num_persons):
            det = self._make_person(i, w, h)
            detections.append(det)

        return sorted(detections, key=lambda d: d.confidence, reverse=True)

    # ── Person factory ────────────────────────────────────────────────────────

    def _make_person(self, index: int, w: int, h: int) -> Detection:
        """
        Generate a plausible bounding box for person `index`.

        Persons are spread across the horizontal field of view at equal angular
        spacing.  Closer persons have taller bounding boxes (perspective scaling).
        """
        n = max(1, self._num_persons)
        # Angular position: spread across [-HFOV/2 + margin, +HFOV/2 - margin]
        hfov_half = self.hfov_deg / 2.0
        margin = hfov_half * 0.1
        if n == 1:
            bearing = 0.0
        else:
            bearing = -hfov_half + margin + index * (self.hfov_deg - 2 * margin) / (n - 1)

        # Convert bearing to image x-centre
        norm_x = (bearing / self.hfov_deg) + 0.5  # 0–1
        cx = int(norm_x * w)
        cy = int(h * 0.5)

        # Bounding box size scales with estimated distance
        distance = self._base_distance + index * self._distance_step
        # At 1 m: person occupies ~0.4 × image width; scales as 1/d
        box_w = max(30, int(w * 0.4 / max(0.3, distance)))
        box_h = max(60, int(box_w * 2.2))  # typical aspect ratio ~2.2
        x = max(0, cx - box_w // 2)
        y = max(0, cy - box_h // 2)
        box_w = min(w - x, box_w)
        box_h = min(h - y, box_h)

        det = Detection(bbox=(x, y, box_w, box_h))
        det.confidence = max(0.5, self._confidence - index * 0.03)
        det.depth_m = distance
        det.bearing_deg = bearing
        return det

    def _make_injected(self, spec: dict, w: int, h: int) -> Detection | None:
        """Build a Detection from a user-supplied spec dict."""
        cx = spec.get("cx_px", w // 2)
        cy = spec.get("cy_px", h // 2)
        box_w = spec.get("box_w", 80)
        box_h = spec.get("box_h", 180)
        dist = spec.get("distance_m", 1.5)
        conf = spec.get("confidence", 0.95)
        bearing = spec.get("bearing_deg", 0.0)

        x = max(0, cx - box_w // 2)
        y = max(0, cy - box_h // 2)

        det = Detection(bbox=(x, y, box_w, box_h))
        det.confidence = conf
        det.depth_m = dist
        det.bearing_deg = bearing
        return det

    # ── Test helpers ──────────────────────────────────────────────────────────

    def set_num_persons(self, n: int) -> None:
        """Dynamically change the person count (useful in parametrised tests)."""
        self._num_persons = n

    def inject_once(self, **kwargs) -> None:
        """Inject a one-shot person on the next call."""
        self._inject_person = kwargs
        self._injected_once = False

    @property
    def call_count(self) -> int:
        return self._call_count
