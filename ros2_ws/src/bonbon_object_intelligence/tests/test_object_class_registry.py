"""Tests for ObjectClassRegistry -- honest class-support answers, never a
hallucinated "supported" for a class the model can't actually produce."""

from __future__ import annotations

import unittest

from bonbon_object_intelligence.core.object_class_registry import ClassStrategy, ObjectClassRegistry


class TestObjectClassRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = ObjectClassRegistry()

    def test_direct_class_is_supported(self):
        self.assertTrue(self.registry.is_supported("person"))
        self.assertEqual(self.registry.strategy_for("person"), ClassStrategy.DIRECT)

    def test_alias_class_is_supported_but_flagged(self):
        self.assertTrue(self.registry.is_supported("child"))
        spec = self.registry.spec_for("child")
        self.assertEqual(spec.strategy, ClassStrategy.ALIAS)
        self.assertTrue(spec.requires_verification)

    def test_ocr_class_is_supported(self):
        self.assertTrue(self.registry.is_supported("room_number_sign"))
        self.assertEqual(self.registry.strategy_for("room_number_sign"), ClassStrategy.OCR)

    def test_unsupported_class_is_honestly_reported(self):
        self.assertFalse(self.registry.is_supported("elevator"))
        self.assertEqual(self.registry.strategy_for("elevator"), ClassStrategy.UNSUPPORTED)

    def test_unknown_class_name_is_unsupported_not_an_error(self):
        self.assertFalse(self.registry.is_supported("spaceship"))

    def test_list_supported_excludes_unsupported(self):
        supported = self.registry.list_supported()
        self.assertIn("person", supported)
        self.assertNotIn("elevator", supported)

    def test_list_unsupported_only_contains_unsupported(self):
        unsupported = self.registry.list_unsupported()
        self.assertIn("elevator", unsupported)
        self.assertIn("wheelchair", unsupported)
        self.assertNotIn("person", unsupported)

    def test_candidates_for_base_class_finds_alias_targets(self):
        candidates = self.registry.candidates_for_base_class("person")
        names = {c.name for c in candidates}
        self.assertIn("person", names)
        self.assertIn("child", names)


if __name__ == "__main__":
    unittest.main()
