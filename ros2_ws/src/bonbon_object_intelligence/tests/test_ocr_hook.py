"""Tests for the OCR hook interface + mock + eligibility check."""

from __future__ import annotations

from bonbon_object_intelligence.core.ocr_hook import MockOCRBackend, is_ocr_eligible


class TestEligibility:
    def test_sign_is_eligible(self):
        assert is_ocr_eligible("sign") is True

    def test_chair_is_not_eligible(self):
        assert is_ocr_eligible("chair") is False


class TestMockBackend:
    def test_mock_is_always_ready(self):
        backend = MockOCRBackend()
        assert backend.is_ready is True

    def test_mock_never_fabricates_text(self):
        backend = MockOCRBackend()
        result = backend.read(b"fake_image_bytes")
        assert result.text == ""
        assert result.confidence == 0.0
        assert result.backend_used == "mock"
