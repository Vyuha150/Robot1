from .mock_person_detector import MockPersonDetector
from .person_detector import Detection, PersonDetector

__all__ = ["PersonDetector", "Detection", "MockPersonDetector"]

try:
    from .hog_person_detector import HogPersonDetector

    __all__.append("HogPersonDetector")
except ImportError:
    pass

try:
    from .yolo_person_detector import YoloPersonDetector

    __all__.append("YoloPersonDetector")
except ImportError:
    pass
