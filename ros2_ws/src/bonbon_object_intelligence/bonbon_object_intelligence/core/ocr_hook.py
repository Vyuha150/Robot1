"""OCR backend interface + mock — for reading signs/documents.

No real OCR engine (e.g. pytesseract/EasyOCR) is a dependency anywhere in
this repo. Same "interface + mock now, real backend later" convention used
throughout bonbon_hal/bonbon_vision/bonbon_gesture for every optional ML
dependency — only runs for OCR-eligible classes, never blocks the main
detection pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

OCR_ELIGIBLE_CLASSES = frozenset({"sign", "document", "book", "menu", "label"})


@dataclass
class OCRResult:
    text: str
    confidence: float
    backend_used: str


class OCRBackendInterface(ABC):
    @abstractmethod
    def read(self, crop_bytes: bytes) -> OCRResult: ...

    @property
    @abstractmethod
    def is_ready(self) -> bool: ...


class MockOCRBackend(OCRBackendInterface):
    """Always returns an empty, zero-confidence result — never fabricates text."""

    @property
    def is_ready(self) -> bool:
        return True

    def read(self, crop_bytes: bytes) -> OCRResult:
        return OCRResult(text="", confidence=0.0, backend_used="mock")


def is_ocr_eligible(class_name: str) -> bool:
    return class_name in OCR_ELIGIBLE_CLASSES
