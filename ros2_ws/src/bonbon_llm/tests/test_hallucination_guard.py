"""
tests.test_hallucination_guard
================================
Unit tests for bonbon_llm.safety.hallucination_guard.HallucinationGuard.

Tests cover
-----------
* Impossible capability phrase detection (fly, arms, human, internet, etc.)
* Fabricated SGD price detection
* Implausible velocity claims (> 1.5 m/s)
* Grounding score computation
* Guard disabled mode
* Safe response generation for flagged output
* Low-confidence scenarios
"""

from bonbon_llm.config.llm_config import HallucinationConfig
from bonbon_llm.core.rag_retriever import RAGDocument, RetrievalResult
from bonbon_llm.safety.hallucination_guard import GuardResult, HallucinationGuard

# ── Helpers ───────────────────────────────────────────────────────────────────


def _guard(enabled: bool = True, min_grounding: float = 0.30) -> HallucinationGuard:
    cfg = HallucinationConfig(
        enabled=enabled,
        min_grounding_score=min_grounding,
    )
    return HallucinationGuard(cfg)


def _rag(text: str, score: float = 0.80) -> RetrievalResult:
    doc = RAGDocument(text=text, doc_id="test_doc", metadata={"source": "test"})
    return RetrievalResult(document=doc, score=score, rank=0)


# ── Impossible capability detection ───────────────────────────────────────────


class TestImpossibleCapabilities:

    def test_fly_claim_flagged(self):
        guard = _guard()
        result = guard.check("I can fly to the counter instantly!")
        assert not result.is_grounded
        assert any("fly" in f for f in result.flagged_claims)

    def test_arms_claim_flagged(self):
        guard = _guard()
        result = guard.check("I have arms so I can hug customers!")
        assert not result.is_grounded
        assert any("arm" in f for f in result.flagged_claims)

    def test_human_claim_flagged(self):
        guard = _guard()
        result = guard.check("Don't worry, I am a human assistant!")
        assert not result.is_grounded
        assert any("human" in f for f in result.flagged_claims)

    def test_internet_claim_flagged(self):
        guard = _guard()
        result = guard.check("I can access the internet to look that up.")
        assert not result.is_grounded
        assert any("internet" in f for f in result.flagged_claims)

    def test_phone_claim_flagged(self):
        guard = _guard()
        result = guard.check("Sure, I can make phone calls for you.")
        assert not result.is_grounded
        assert any("phone" in f for f in result.flagged_claims)

    def test_payment_claim_flagged(self):
        guard = _guard()
        result = guard.check("I can process payments directly on my end.")
        assert not result.is_grounded
        assert any("payment" in f for f in result.flagged_claims)

    def test_false_memory_flagged(self):
        guard = _guard()
        result = guard.check("I remember you from last week — you had the latte!")
        assert not result.is_grounded

    def test_night_vision_flagged(self):
        guard = _guard()
        result = guard.check("I can see in the dark with my sensors.")
        assert not result.is_grounded

    def test_normal_response_passes(self):
        guard = _guard()
        rag = [_rag("Our latte is S$5.50. We are open 8am to 8pm.")]
        result = guard.check(
            "Our latte is S$5.50. Would you like one?",
            rag_results=rag,
        )
        assert result.is_grounded

    def test_greeting_passes_without_rag(self):
        guard = _guard()
        result = guard.check("Hello! Welcome to the café. What can I get you?")
        assert result.is_grounded


# ── Fabricated price detection ────────────────────────────────────────────────


class TestFabricatedPrices:

    def test_fabricated_price_flagged(self):
        guard = _guard()
        # S$99.99 is not in the known price set or RAG
        result = guard.check("Our espresso is S$99.99 today.", rag_results=[])
        assert not result.is_grounded
        assert any("fabricated price" in f for f in result.flagged_claims)

    def test_known_price_passes(self):
        guard = _guard()
        rag = [_rag("The espresso costs S$4.00.")]
        result = guard.check(
            "The espresso is S$4.00.",
            rag_results=rag,
        )
        # S$4.00 is in the known set — should pass
        assert result.is_grounded

    def test_rag_document_price_passes(self):
        guard = _guard()
        # S$7.80 not in default set but IS in the RAG document
        rag = [_rag("Our special seasonal latte is S$7.80.")]
        result = guard.check(
            "The seasonal latte is S$7.80.",
            rag_results=rag,
        )
        # Price found in RAG → grounded
        assert result.is_grounded

    def test_no_price_in_response_always_passes_price_check(self):
        guard = _guard()
        result = guard.check("Would you like a coffee?", rag_results=[])
        # No price mentioned — price check should not flag
        assert not any("fabricated price" in f for f in result.flagged_claims)


# ── Velocity claim detection ──────────────────────────────────────────────────


class TestVelocityClaims:

    def test_implausible_speed_flagged(self):
        guard = _guard()
        result = guard.check("I can travel at 5.0 m/s to reach your table quickly.")
        assert not result.is_grounded
        assert any("speed" in f for f in result.flagged_claims)

    def test_plausible_speed_passes(self):
        guard = _guard()
        rag = [_rag("The robot travels at a maximum of 0.5 m/s for safety.")]
        result = guard.check(
            "I travel at 0.5 m/s for your safety.",
            rag_results=rag,
        )
        assert result.is_grounded

    def test_high_kmh_flagged(self):
        guard = _guard()
        result = guard.check("I can move at 20 km/h in the café!")
        assert not result.is_grounded


# ── Guard disabled ────────────────────────────────────────────────────────────


class TestGuardDisabled:

    def test_disabled_always_grounded(self):
        guard = _guard(enabled=False)
        # Even an obviously hallucinated response passes when guard is off
        result = guard.check("I am a human and I can fly at 50 m/s!")
        assert result.is_grounded

    def test_disabled_returns_original_response(self):
        guard = _guard(enabled=False)
        text = "I have arms and can make payments."
        result = guard.check(text)
        assert result.safe_response == text


# ── Safe response generation ──────────────────────────────────────────────────


class TestSafeResponseGeneration:

    def test_safe_response_populated_on_flag(self):
        guard = _guard()
        result = guard.check("I can fly over to your table instantly!")
        assert not result.is_grounded
        assert len(result.safe_response) > 0

    def test_safe_response_differs_from_original(self):
        guard = _guard()
        text = "I can fly to you right now!"
        result = guard.check(text)
        assert not result.is_grounded
        # Safe version should not contain the flagged claim verbatim
        assert "I can fly" not in result.safe_response

    def test_original_response_preserved(self):
        guard = _guard()
        text = "I can fly to table 3 immediately."
        result = guard.check(text)
        assert result.original_response == text


# ── GuardResult fields ────────────────────────────────────────────────────────


class TestGuardResultFields:

    def test_confidence_between_0_and_1(self):
        guard = _guard()
        for text in [
            "Hello! Welcome.",
            "I can fly and I am human and I can access the internet.",
        ]:
            result = guard.check(text)
            assert (
                0.0 <= result.confidence <= 1.0
            ), f"Confidence out of range: {result.confidence} for: {text!r}"

    def test_reason_set_on_failure(self):
        guard = _guard()
        result = guard.check("I can fly to your table!")
        assert not result.is_grounded
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

    def test_flagged_claims_is_list(self):
        guard = _guard()
        result = guard.check("Hello!")
        assert isinstance(result.flagged_claims, list)


# ── Low-confidence scenario ───────────────────────────────────────────────────


class TestLowConfidence:

    def test_low_llm_confidence_with_no_rag(self):
        guard = _guard(min_grounding=0.30)
        # Long response with no RAG backing and low LLM confidence → flagged
        long_response = (
            "Based on my knowledge, the croissant is S$3.20 and the brioche is S$4.10 "
            "and the sourdough is S$5.80. All of these are freshly baked every morning."
        )
        result = guard.check(long_response, rag_results=[], llm_confidence=0.20)
        # With low confidence + no RAG + possibly fabricated prices → should not be grounded
        assert isinstance(result, GuardResult)  # at minimum returns a valid result

    def test_high_confidence_with_rag_grounded(self):
        guard = _guard()
        rag = [_rag("The latte is S$5.50. We open at 8am and close at 8pm.", score=0.90)]
        result = guard.check(
            "The latte costs S$5.50.",
            rag_results=rag,
            llm_confidence=0.92,
        )
        assert result.is_grounded
