"""ObjectClassRegistry — the honest answer to "what objects can BonBon
actually recognize."

The base detector (bonbon_vision) only ever produces COCO's 80 generic
classes (see docs/OBJECT_RECOGNITION_FAILURE_ANALYSIS.md). This registry
maps the ~30 service-environment classes the product actually needs onto
one of four honest strategies -- it never invents a detection the base
model didn't produce:

  DIRECT       the required class IS one of the base model's classes
               (e.g. "phone" -> COCO "cell phone").
  ALIAS        the required class is approximated by a base class, but
               needs `ObjectVerificationManager` confirmation before the
               alias label is trusted (e.g. "child" -> "person" + a
               size/geometry check).
  OCR          the required class is only readable via OCR on the region
               (signs, documents, ID cards, room numbers) -- gated by
               `enable_ocr` and `bonbon_object_intelligence.core.ocr_hook`.
  UNSUPPORTED  no strategy exists today. Reported honestly as unsupported;
               never silently mapped to a base class that would make a
               false detection look real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ClassStrategy(StrEnum):
    DIRECT = "direct"
    ALIAS = "alias"
    OCR = "ocr"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ClassSpec:
    name: str
    strategy: ClassStrategy
    base_class: str | None = None
    requires_verification: bool = False
    note: str = ""


# The ~30 required service-environment classes, each honestly classified.
# `base_class` for DIRECT/ALIAS is the COCO label the base detector
# actually produces today.
DEFAULT_CLASS_SPECS: dict[str, ClassSpec] = {
    spec.name: spec
    for spec in [
        ClassSpec("person", ClassStrategy.DIRECT, base_class="person"),
        ClassSpec(
            "child",
            ClassStrategy.ALIAS,
            base_class="person",
            requires_verification=True,
            note="COCO has no age classes; verified via bbox-height heuristic",
        ),
        ClassSpec("elderly_person", ClassStrategy.UNSUPPORTED, note="no classifier available"),
        ClassSpec("wheelchair_user", ClassStrategy.UNSUPPORTED, note="no classifier available"),
        ClassSpec("wheelchair", ClassStrategy.UNSUPPORTED, note="no reliable COCO alias exists"),
        ClassSpec(
            "hospital_bed",
            ClassStrategy.ALIAS,
            base_class="bed",
            requires_verification=True,
            note="COCO 'bed' is a reasonable base; verification narrows false positives",
        ),
        ClassSpec("chair", ClassStrategy.DIRECT, base_class="chair"),
        ClassSpec("table", ClassStrategy.DIRECT, base_class="dining table"),
        ClassSpec("reception_counter", ClassStrategy.UNSUPPORTED),
        ClassSpec("door", ClassStrategy.UNSUPPORTED, note="no COCO class"),
        ClassSpec("elevator", ClassStrategy.UNSUPPORTED),
        ClassSpec("lift_button", ClassStrategy.UNSUPPORTED),
        ClassSpec("room_number_sign", ClassStrategy.OCR),
        ClassSpec("signboard", ClassStrategy.OCR),
        ClassSpec("document", ClassStrategy.OCR, note="also aliasable from COCO 'book'"),
        ClassSpec("ID_card", ClassStrategy.OCR),
        ClassSpec("phone", ClassStrategy.DIRECT, base_class="cell phone"),
        ClassSpec(
            "bag",
            ClassStrategy.ALIAS,
            base_class="backpack",
            requires_verification=True,
            note="also matches COCO 'handbag'/'suitcase'",
        ),
        ClassSpec("bottle", ClassStrategy.DIRECT, base_class="bottle"),
        ClassSpec("tray", ClassStrategy.UNSUPPORTED),
        ClassSpec("medicine_box", ClassStrategy.UNSUPPORTED),
        ClassSpec("food_packet", ClassStrategy.UNSUPPORTED),
        ClassSpec("laptop", ClassStrategy.DIRECT, base_class="laptop"),
        ClassSpec("cable_on_floor", ClassStrategy.UNSUPPORTED, note="needs a floor-hazard model"),
        ClassSpec("wet_floor_sign", ClassStrategy.OCR),
        ClassSpec(
            "fallen_object", ClassStrategy.UNSUPPORTED, note="needs temporal/state reasoning"
        ),
        ClassSpec("trolley", ClassStrategy.UNSUPPORTED),
        ClassSpec("cart", ClassStrategy.UNSUPPORTED),
        ClassSpec("dustbin", ClassStrategy.UNSUPPORTED),
        ClassSpec("stairs", ClassStrategy.UNSUPPORTED),
        ClassSpec("ramp", ClassStrategy.UNSUPPORTED),
    ]
}


@dataclass
class ObjectClassRegistry:
    specs: dict[str, ClassSpec] = field(default_factory=lambda: dict(DEFAULT_CLASS_SPECS))

    def is_supported(self, name: str) -> bool:
        spec = self.specs.get(name)
        return spec is not None and spec.strategy != ClassStrategy.UNSUPPORTED

    def strategy_for(self, name: str) -> ClassStrategy:
        spec = self.specs.get(name)
        return spec.strategy if spec else ClassStrategy.UNSUPPORTED

    def spec_for(self, name: str) -> ClassSpec | None:
        return self.specs.get(name)

    def list_supported(self) -> list[str]:
        return sorted(n for n, s in self.specs.items() if s.strategy != ClassStrategy.UNSUPPORTED)

    def list_unsupported(self) -> list[str]:
        return sorted(n for n, s in self.specs.items() if s.strategy == ClassStrategy.UNSUPPORTED)

    def candidates_for_base_class(self, base_class: str) -> list[ClassSpec]:
        """Every required class a raw detection of `base_class` (a COCO
        label) could honestly be reported as -- DIRECT matches always,
        ALIAS matches only after ObjectVerificationManager confirms."""
        return [s for s in self.specs.values() if s.base_class == base_class]
