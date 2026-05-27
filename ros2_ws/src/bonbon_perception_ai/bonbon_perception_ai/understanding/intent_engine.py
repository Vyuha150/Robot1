"""
bonbon_perception_ai.understanding.intent_engine
================================================
Classifies a SpeechInput into a structured UserIntent.

Backends
--------
rule_based (default)
    Regex pattern matching + slot filling. Zero latency, no external deps.
    Suitable for production on embedded hardware.

langchain (optional)
    Uses a LangChain chain with an OpenAI-compatible LLM.
    API key is NEVER hardcoded — injected via config (ROS2 param) or the
    OPENAI_API_KEY environment variable.
    Falls back to rule_based on timeout or exception.

Uncertainty handling
--------------------
When confidence < intent_confidence_threshold:
  - ambiguity_policy = "clarify"    → publish is_ambiguous=True + fallback_response
  - ambiguity_policy = "best_guess" → publish best-guess with is_ambiguous=True
  - ambiguity_policy = "ignore"     → return None (caller must handle)
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from bonbon_perception_ai.config.perception_config import IntentConfig
from bonbon_perception_ai.fusion.types import FusionContext, SpeechInput

# ── Output types ──────────────────────────────────────────────────────────────


@dataclass
class IntentSlot:
    name: str
    value: str
    confidence: float = 0.85


@dataclass
class UserIntent:
    intent_class: str
    confidence: float
    speaker_id: str
    raw_text: str
    slots: list[IntentSlot] = field(default_factory=list)
    is_ambiguous: bool = False
    fallback_response: str = ""
    speech_confidence: float = 1.0
    intent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def slot_dict(self) -> dict[str, str]:
        return {s.name: s.value for s in self.slots}


# ── Intent / slot pattern tables ──────────────────────────────────────────────

# Each value is a list of regex patterns; any match scores that intent.
# Patterns use case-insensitive matching via re.IGNORECASE.
INTENT_PATTERNS: dict[str, list[str]] = {
    "order_item": [
        r"\b(order|bring|get|want|give\s+me|i['\s]?d\s+like|can\s+i\s+have|may\s+i\s+have)\b",
        r"\b(coffee|tea|water|juice|food|drink|snack|meal|item|menu)\b",
    ],
    "navigate_to": [
        r"\b(go\s+to|move\s+to|take\s+me\s+to|navigate\s+to|head\s+to|go\s+back\s+to)\b",
        r"\b(follow\s+me|come\s+here|come\s+to\s+me|come\s+with\s+me)\b",
    ],
    "ask_question": [
        r"^(what|where|when|how|why|who|which|do\s+you|can\s+you|could\s+you|tell\s+me)\b",
    ],
    "cancel": [
        r"\b(stop|cancel|abort|never\s+mind|forget\s+it|don['\s]?t|halt|quit)\b",
    ],
    "confirm": [
        r"^(yes|yeah|yep|correct|that['\s]?s\s+right|sure|ok|okay|please|go\s+ahead|perfect)\b",
    ],
    "deny": [
        r"^(no|nope|wrong|not\s+that|that['\s]?s\s+not|don['\s]?t\s+want)\b",
    ],
    "help_request": [
        r"\b(help|assist|support|emergency|i\s+need\s+help|call\s+someone)\b",
    ],
    "greeting": [
        r"^(hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening|greetings|howdy)\b",
    ],
}

SLOT_PATTERNS: dict[str, str] = {
    "item": r"\b(coffee|tea|water|juice|food|sandwich|cake|cookie|meal|drink|snack)\b",
    "destination": r"\b(table\s*\d+|room\s*\w+|entrance|exit|kitchen|reception|lobby|hallway|door|counter)\b",
    "quantity": r"\b(\d+|one|two|three|four|five|six|a\s+couple|a\s+few)\b",
    "person_ref": r"\b(me|us|them|him|her|the\s+person|customer|guest|man|woman|child)\b",
}

_CLARIFY_RESPONSES = {
    "order_item": "What item would you like to order?",
    "navigate_to": "Where would you like me to go?",
    "unknown": "I'm not sure I understood that. Could you please repeat or rephrase?",
}

_DEFAULT_CLARIFY = "I'm sorry, I didn't quite catch that. Could you say that again?"


class IntentEngine:
    """
    Classifies SpeechInput → UserIntent using rule-based patterns or LangChain.

    Usage
    -----
    engine = IntentEngine(cfg)
    intent = engine.classify(speech_input, fusion_context)
    """

    def __init__(self, cfg: IntentConfig) -> None:
        self.cfg = cfg
        self._lc_chain = None  # lazy-loaded if backend == "langchain"
        self._compiled: dict[str, list[re.Pattern]] = {
            intent: [re.compile(p, re.IGNORECASE) for p in patterns]
            for intent, patterns in INTENT_PATTERNS.items()
        }
        self._slot_compiled: dict[str, re.Pattern] = {
            name: re.compile(p, re.IGNORECASE) for name, p in SLOT_PATTERNS.items()
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def classify(
        self,
        speech: SpeechInput,
        ctx: FusionContext,
    ) -> UserIntent | None:
        """
        Classify speech into a UserIntent.

        Returns None only when ambiguity_policy == "ignore" and confidence
        is below threshold.
        """
        # Empty / silence / timeout → silence intent
        if not speech.is_valid:
            return UserIntent(
                intent_class="silence",
                confidence=1.0,
                speaker_id=speech.speaker_id,
                raw_text=speech.text,
                speech_confidence=speech.confidence,
            )

        # Apply privacy: optionally suppress speaker ID
        speaker_id = speech.speaker_id

        # Step 1: rule-based classification
        intent_class, confidence = self._rule_based(speech.text)

        # Step 2: optional LangChain refinement on low-confidence results
        if confidence < self.cfg.intent_confidence_threshold and self.cfg.backend == "langchain":
            try:
                lc_class, lc_conf = self._langchain_classify(speech.text, ctx)
                if lc_conf > confidence:
                    intent_class, confidence = lc_class, lc_conf
            except Exception:
                pass  # LangChain failed → stick with rule-based result

        slots = self._extract_slots(speech.text)
        ambiguous = confidence < self.cfg.intent_confidence_threshold

        if ambiguous:
            if self.cfg.ambiguity_policy == "ignore":
                return None
            fallback = _CLARIFY_RESPONSES.get(intent_class, _DEFAULT_CLARIFY)
            if self.cfg.ambiguity_policy == "best_guess":
                pass  # keep intent_class as best guess
            else:  # "clarify"
                intent_class = "unknown"
        else:
            fallback = ""

        return UserIntent(
            intent_class=intent_class,
            confidence=confidence,
            speaker_id=speaker_id,
            raw_text=speech.text,
            slots=slots,
            is_ambiguous=ambiguous,
            fallback_response=fallback,
            speech_confidence=speech.confidence,
        )

    # ── Rule-based classification ─────────────────────────────────────────────

    def _rule_based(self, text: str) -> tuple[str, float]:
        scores: dict[str, float] = {}
        for intent_class, patterns in self._compiled.items():
            hits = sum(1 for p in patterns if p.search(text))
            if hits > 0:
                # Each additional pattern hit bumps confidence
                scores[intent_class] = min(0.58 + 0.20 * hits, 0.96)

        if not scores:
            return "unknown", 0.10

        best = max(scores, key=lambda k: scores[k])

        # Conflict: two intents within 0.05 of each other → ambiguous
        sorted_scores = sorted(scores.values(), reverse=True)
        if len(sorted_scores) >= 2 and (sorted_scores[0] - sorted_scores[1]) < 0.05:
            return best, sorted_scores[0] * 0.80  # penalise for ambiguity

        return best, scores[best]

    # ── Slot extraction ───────────────────────────────────────────────────────

    def _extract_slots(self, text: str) -> list[IntentSlot]:
        slots: list[IntentSlot] = []
        for slot_name, pattern in self._slot_compiled.items():
            m = pattern.search(text)
            if m:
                slots.append(
                    IntentSlot(
                        name=slot_name,
                        value=m.group(0).strip().lower(),
                        confidence=0.85,
                    )
                )
        return slots

    # ── LangChain backend (optional) ──────────────────────────────────────────

    def _langchain_classify(self, text: str, ctx: FusionContext) -> tuple[str, float]:
        """
        Use a LangChain chain to classify intent.

        Raises on any error (caller catches and falls back to rule-based).
        Never hardcodes the API key — uses cfg.langchain_api_key or the
        OPENAI_API_KEY environment variable.
        """
        if self._lc_chain is None:
            self._lc_chain = self._build_lc_chain()

        scene_ctx = (
            f"persons={ctx.person_count} " f"speech_stale={'speech' in ctx.stale_modalities}"
        )
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(
                self._lc_chain.invoke,
                {
                    "text": text,
                    "context": scene_ctx,
                    "valid_classes": ", ".join(INTENT_PATTERNS.keys()),
                },
            )
            result = fut.result(timeout=self.cfg.langchain_timeout_sec)

        # Parse "intent_class|confidence" response
        parts = str(result).strip().split("|")
        if len(parts) == 2:
            cls = parts[0].strip().lower()
            conf = float(parts[1].strip())
            if cls in INTENT_PATTERNS:
                return cls, min(1.0, max(0.0, conf))

        raise ValueError(f"Unexpected LangChain response: {result!r}")

    def _build_lc_chain(self):
        import os

        from langchain.chains import LLMChain  # type: ignore
        from langchain.prompts import PromptTemplate  # type: ignore

        try:
            from langchain_openai import ChatOpenAI  # type: ignore
        except ImportError:
            from langchain.chat_models import ChatOpenAI  # type: ignore

        api_key = self.cfg.langchain_api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "LangChain backend requires an API key — set intent.langchain_api_key "
                "ROS2 param or OPENAI_API_KEY env var."
            )

        llm = ChatOpenAI(
            model=self.cfg.langchain_model,
            openai_api_key=api_key,
            temperature=0,
            request_timeout=self.cfg.langchain_timeout_sec,
        )
        prompt = PromptTemplate(
            input_variables=["text", "context", "valid_classes"],
            template=(
                "You are an intent classifier for a service robot.\n"
                "Scene context: {context}\n"
                "Valid intent classes: {valid_classes}\n"
                'User said: "{text}"\n'
                "Respond with exactly: <intent_class>|<confidence 0.0-1.0>\n"
                "Example: order_item|0.92"
            ),
        )
        return LLMChain(llm=llm, prompt=prompt)
