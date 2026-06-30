"""Perception checks: right person, no identity mix-up, low confidence
handled correctly. Feeds oracle checks #2, #3, #5."""

from __future__ import annotations

from bonbon_behavior_validation.expected_outcomes import (
    CheckResult,
    CheckStatus,
    ExpectedOutcome,
    ObservedOutcome,
)


def responded_to_correct_person(observed: ObservedOutcome) -> CheckResult:
    if observed.expected_person_id is None:
        return CheckResult(
            "responded_to_correct_person", CheckStatus.NOT_APPLICABLE, "no addressee expected"
        )
    ok = observed.responded_to_person_id == observed.expected_person_id
    return CheckResult(
        "responded_to_correct_person",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        f"responded_to={observed.responded_to_person_id} expected={observed.expected_person_id}",
    )


def no_identity_mixup(expected: ExpectedOutcome, observed: ObservedOutcome) -> CheckResult:
    if not expected.requires_identity_disambiguation:
        return CheckResult(
            "no_identity_mixup", CheckStatus.NOT_APPLICABLE, "single, unambiguous person"
        )
    ok = not observed.identity_mixup_detected
    return CheckResult(
        "no_identity_mixup",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        "no mix-up detected" if ok else "identity mix-up detected",
    )


def low_confidence_handled_correctly(
    expected: ExpectedOutcome, observed: ObservedOutcome
) -> CheckResult:
    if observed.detection_confidence is None:
        return CheckResult(
            "low_confidence_handling", CheckStatus.NOT_APPLICABLE, "no confidence score produced"
        )
    if observed.detection_confidence >= expected.confidence_threshold:
        return CheckResult(
            "low_confidence_handling", CheckStatus.NOT_APPLICABLE, "confidence above threshold"
        )
    # Below threshold: must not have been asserted as fact -- either a
    # clarification was asked or no strong action was taken on it.
    ok = observed.asked_clarification or not observed.unsafe_movement_executed
    return CheckResult(
        "low_confidence_handling",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        f"confidence={observed.detection_confidence} below threshold {expected.confidence_threshold}",
    )


def detection_within_iou_and_class(
    observed_class: str, expected_class: str, observed_iou: float, iou_threshold: float = 0.5
) -> CheckResult:
    ok = observed_class == expected_class and observed_iou >= iou_threshold
    return CheckResult(
        "detection_within_iou_and_class",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        f"class={observed_class}/{expected_class} iou={observed_iou}",
    )
