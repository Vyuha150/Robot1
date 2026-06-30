"""Speech/dialogue checks: clarification asked when needed, transcript
fidelity, emergency-phrase escalation. Feeds oracle check #6."""

from __future__ import annotations

from bonbon_behavior_validation.expected_outcomes import (
    CheckResult,
    CheckStatus,
    ExpectedOutcome,
    ObservedOutcome,
)


def asked_clarification_when_needed(
    expected: ExpectedOutcome, observed: ObservedOutcome
) -> CheckResult:
    if not expected.requires_clarification:
        return CheckResult(
            "clarification_when_needed", CheckStatus.NOT_APPLICABLE, "input was unambiguous"
        )
    ok = observed.asked_clarification
    return CheckResult(
        "clarification_when_needed",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        "clarification asked" if ok else "ambiguous input but no clarification was asked",
    )


def _word_error_rate(observed_transcript: str, expected_transcript: str) -> float:
    obs_words = observed_transcript.lower().split()
    exp_words = expected_transcript.lower().split()
    if not exp_words:
        return 0.0 if not obs_words else 1.0
    # Levenshtein distance over words.
    prev = list(range(len(obs_words) + 1))
    for i, ew in enumerate(exp_words, start=1):
        cur = [i] + [0] * len(obs_words)
        for j, ow in enumerate(obs_words, start=1):
            cost = 0 if ew == ow else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1] / len(exp_words)


def transcript_matches(
    observed_transcript: str, expected_transcript: str, wer_budget: float = 0.2
) -> CheckResult:
    wer = _word_error_rate(observed_transcript, expected_transcript)
    ok = wer <= wer_budget
    return CheckResult(
        "transcript_matches",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        f"WER={wer:.2f} budget={wer_budget}",
    )


def emergency_phrase_escalated(expected: ExpectedOutcome, observed: ObservedOutcome) -> CheckResult:
    if not expected.is_emergency:
        return CheckResult(
            "emergency_phrase_escalated", CheckStatus.NOT_APPLICABLE, "not an emergency scenario"
        )
    ok = observed.safety_decision == "blocked" or observed.estop_triggered or observed.event_logged
    return CheckResult(
        "emergency_phrase_escalated",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        "escalated" if ok else "emergency phrase/gesture was not escalated",
    )
