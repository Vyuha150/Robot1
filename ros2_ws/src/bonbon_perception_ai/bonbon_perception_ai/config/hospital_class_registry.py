"""hospital_class_registry — Phase 7's "supported class registry / custom
hospital class config": the exact set of object classes BonBon's
perception stack is allowed to report, and the hospital-specific subset
worth calling out on the dashboard separately from generic COCO classes.
Rule: "unsupported classes must not be hallucinated" -- any detector
result whose class label is not in SUPPORTED_CLASSES must be dropped
before it reaches the fusion layer, never passed through as-is.

This registry does NOT own detection itself (see
docs/AI_MODEL_GAP_ANALYSIS.md GAP-2 for why object detection has 3
separate implementations today, and why consolidating them is deferred
to a follow-up pass rather than attempted blind in this one) -- it is
the class allowlist any of those three detectors' output should be
filtered through.
"""

from __future__ import annotations

# Standard COCO classes BonBon's YOLO-family detectors (whichever backend
# is active) can report -- kept to the subset actually relevant to a
# hospital reception setting, not the full 80-class COCO list, so a
# detector misfiring "toaster" or "giraffe" in a hospital lobby is
# dropped rather than surfaced.
SUPPORTED_GENERIC_CLASSES = frozenset({
    "person", "chair", "bench", "backpack", "handbag", "suitcase",
    "umbrella", "cell phone", "laptop", "bottle", "cup", "book",
})

# Hospital-specific classes -- not part of standard COCO, would require a
# custom-trained or fine-tuned model to actually detect. None of these
# are backed by a real trained model in this pass (HARDWARE_BLOCKED /
# MISSING per the Phase 1 audit) -- listed here as the target taxonomy
# for when/if a custom model is trained, not a claim that detection
# exists today.
HOSPITAL_SPECIFIC_CLASSES = frozenset({
    "wheelchair", "stretcher", "iv_stand", "hospital_bed", "walker", "crutches",
})

SUPPORTED_CLASSES = SUPPORTED_GENERIC_CLASSES | HOSPITAL_SPECIFIC_CLASSES


def filter_detections(detections: list[dict]) -> list[dict]:
    """detections: list of {"class_name": str, ...}. Drops (does not
    relabel or guess) any detection whose class isn't in the allowlist --
    matches the rule that unsupported classes must never be hallucinated
    into a supported one."""
    return [d for d in detections if d.get("class_name") in SUPPORTED_CLASSES]


def is_hospital_specific(class_name: str) -> bool:
    return class_name in HOSPITAL_SPECIFIC_CLASSES
