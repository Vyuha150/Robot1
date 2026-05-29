"""Rule-based text emotion analyzer for BonBon's service-robot context."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from ..config.affective_config import AffectiveConfig
    from ..privacy.privacy_gate import PrivacyGate

logger = logging.getLogger(__name__)

# ── Keyword sets ──────────────────────────────────────────────────────────────

EMERGENCY_KEYWORDS: frozenset[str] = frozenset({
    "help", "emergency", "fallen", "fall", "fell", "hurt", "pain",
    "call nurse", "call doctor", "i need help", "dying", "can't breathe",
    "chest pain", "unconscious",
})

DISTRESS_KEYWORDS: frozenset[str] = frozenset({
    "upset", "worried", "scared", "frightened", "anxious", "terrible",
    "awful", "miserable", "crying", "sobbing", "desperate", "hopeless",
})

ANGER_KEYWORDS: frozenset[str] = frozenset({
    "angry", "furious", "ridiculous", "unacceptable", "complaint",
    "awful service", "outraged", "disgusting", "infuriated", "incompetent",
    "demand", "demanding",
})

CONFUSION_KEYWORDS: frozenset[str] = frozenset({
    "confused", "don't understand", "what do you mean", "how do i",
    "i don't know", "unclear", "lost", "bewildered", "not sure",
    "could you explain", "what is", "which way",
})

GRATITUDE_KEYWORDS: frozenset[str] = frozenset({
    "thank you", "thanks", "appreciate", "grateful", "wonderful",
    "excellent", "brilliant", "fantastic", "so kind", "lovely",
    "great job", "well done",
})

MEDICAL_KEYWORDS: frozenset[str] = frozenset({
    "doctor", "nurse", "medicine", "hospital", "ward", "prescription",
    "pill", "pills", "injection", "sick", "ill", "medication", "dosage",
    "treatment", "symptom", "symptoms",
})

SAFETY_KEYWORDS: frozenset[str] = frozenset({
    "fire", "smoke", "flood", "gas leak", "alarm", "evacuation",
    "call police", "intruder", "danger", "unsafe",
})

COMPLAINT_KEYWORDS: frozenset[str] = frozenset({
    "complaint", "complain", "not happy", "disappointed", "broken",
    "not working", "problem with", "issue with", "should be", "poor",
})

REQUEST_KEYWORDS: frozenset[str] = frozenset({
    "please", "can you", "could you", "would you", "i need", "i want",
    "bring me", "show me", "help me", "find me", "take me",
})


def _score_keywords(text_lower: str, keywords: frozenset[str]) -> float:
    """Count how many keyword phrases appear in *text_lower* and normalise.

    Args:
        text_lower: Lower-cased input text.
        keywords: Set of keyword phrases to search for.

    Returns:
        float: Score in [0.0, 1.0]; grows with the number of matched phrases,
            capped at 1.0.
    """
    hits: int = sum(1 for kw in keywords if kw in text_lower)
    return min(hits / max(1, min(len(keywords), 5)), 1.0)


class TextEmotionAnalyzer:
    """Rule-based text emotion analyzer for service-robot scenarios.

    Operates entirely without ML models, making it suitable for environments
    where the ML stack has not loaded yet or has failed.  All scoring is based
    on keyword matching with normalised confidence.

    The analyzer also supports a 'transformer' backend path that imports a
    Hugging Face pipeline if available; this path is inactive by default
    (``text_backend = "rules"``) and falls back to rules gracefully.
    """

    def __init__(
        self,
        config: "AffectiveConfig",
        privacy_gate: "PrivacyGate",
        node_clock,
    ) -> None:
        """Initialise the analyzer.

        Args:
            config: Active configuration dataclass.
            privacy_gate: Gate controlling privacy suppression.
            node_clock: The ``node.get_clock()`` clock for message stamps.
        """
        self._config = config
        self._privacy = privacy_gate
        self._clock = node_clock
        self._transformer_pipeline = None
        self._backend_label: str = config.text_backend

        if config.text_backend == "transformer":
            self._try_load_transformer()

    # ── Public interface ──────────────────────────────────────────────────────

    def analyze_text(
        self,
        text: str,
        person_id: str = "",
        tracking_id: int = 0,
        context: str = "",
    ):
        """Analyse a text string and return a ``TextEmotion`` message.

        Always returns a message (never None) because text analysis has no
        rate-limit and the rule engine never fails.

        Args:
            text: Input text to analyse (e.g. from speech-to-text).
            person_id: Optional person identifier.
            tracking_id: Optional tracking ID.
            context: Optional context hint (unused by rule engine but passed
                to transformer if available).

        Returns:
            TextEmotion: Populated ROS2 message.
        """
        if self._privacy.should_suppress_text():
            return self._make_suppressed_msg(person_id, tracking_id)

        scores: Dict[str, float] = self._score_rules(text)

        if (
            self._config.text_backend == "transformer"
            and self._transformer_pipeline is not None
        ):
            scores = self._merge_transformer(text, scores)

        return self._build_msg(text, scores, person_id, tracking_id)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_rules(self, text: str) -> Dict[str, float]:
        """Apply all keyword sets and return a score dictionary.

        Args:
            text: Raw input text.

        Returns:
            dict: Keys are emotion/intent category names mapped to float
                scores in [0.0, 1.0].
        """
        lower: str = text.lower()
        return {
            "emergency": _score_keywords(lower, EMERGENCY_KEYWORDS),
            "distress": _score_keywords(lower, DISTRESS_KEYWORDS),
            "anger": _score_keywords(lower, ANGER_KEYWORDS),
            "confusion": _score_keywords(lower, CONFUSION_KEYWORDS),
            "gratitude": _score_keywords(lower, GRATITUDE_KEYWORDS),
            "medical": _score_keywords(lower, MEDICAL_KEYWORDS),
            "safety": _score_keywords(lower, SAFETY_KEYWORDS),
            "complaint": _score_keywords(lower, COMPLAINT_KEYWORDS),
            "request": _score_keywords(lower, REQUEST_KEYWORDS),
            "neutral": 0.0,  # filled below as residual
        }

    # ── Transformer path ──────────────────────────────────────────────────────

    def _try_load_transformer(self) -> None:
        """Attempt to load a Hugging Face sentiment pipeline.

        Falls back to rules if the package is not installed.
        """
        try:
            from transformers import pipeline  # type: ignore[import]

            self._transformer_pipeline = pipeline(
                "text-classification",
                model="bhadresh-savani/distilbert-base-uncased-emotion",
                top_k=None,
            )
            logger.info("Transformer text backend loaded.")
            self._backend_label = "transformer"
        except ImportError:
            logger.warning(
                "transformers package not installed.  "
                "Falling back to rule-based text analysis."
            )
            self._backend_label = "rules"
        except Exception as exc:
            logger.warning("Transformer load failed: %s.  Using rules.", exc)
            self._backend_label = "rules"

    def _merge_transformer(
        self, text: str, rule_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Merge transformer output into rule scores with equal weighting.

        Args:
            text: Input text.
            rule_scores: Scores from the rule engine.

        Returns:
            dict: Merged scores (element-wise average where keys overlap).
        """
        try:
            results = self._transformer_pipeline(text[:512])
            if isinstance(results, list) and results:
                if isinstance(results[0], list):
                    results = results[0]
                for item in results:
                    label: str = item["label"].lower()
                    score: float = float(item["score"])
                    if label in rule_scores:
                        rule_scores[label] = (rule_scores[label] + score) / 2.0
                    elif label == "joy":
                        rule_scores["gratitude"] = max(
                            rule_scores.get("gratitude", 0.0), score
                        )
                    elif label == "sadness":
                        rule_scores["distress"] = max(
                            rule_scores.get("distress", 0.0), score
                        )
        except Exception as exc:
            logger.debug("Transformer inference failed: %s", exc)
        return rule_scores

    # ── Message builders ──────────────────────────────────────────────────────

    def _build_msg(
        self,
        text: str,
        scores: Dict[str, float],
        person_id: str,
        tracking_id: int,
    ):
        """Construct a TextEmotion message from scoring results.

        Args:
            text: Original input text (truncated to 200 chars in the message).
            scores: Score dictionary from rule engine / transformer.
            person_id: String person identifier.
            tracking_id: Integer tracking ID.

        Returns:
            TextEmotion: Fully populated ROS2 message.
        """
        from bonbon_msgs.msg import TextEmotion  # type: ignore[import]

        # Determine dominant category.
        # Emergency always wins if its score is > 0.
        score_order: list[str] = [
            "emergency", "distress", "safety", "medical",
            "anger", "confusion", "complaint", "gratitude", "request",
        ]
        dominant: str = "neutral"
        dominant_conf: float = 0.0
        for cat in score_order:
            if scores.get(cat, 0.0) > dominant_conf:
                dominant = cat
                dominant_conf = scores[cat]

        # Neutral as residual when nothing matched strongly.
        if dominant_conf < self._config.text_confidence_threshold:
            dominant = "neutral"
            scores["neutral"] = 1.0 - dominant_conf
            dominant_conf = scores["neutral"]

        # Derived boolean flags.
        emergency = scores.get("emergency", 0.0) > 0.0
        distress = scores.get("distress", 0.0) > 0.1
        medical = scores.get("medical", 0.0) > 0.1
        safety_concern = scores.get("safety", 0.0) > 0.1
        anger = scores.get("anger", 0.0) > 0.1
        confusion = scores.get("confusion", 0.0) > 0.1
        requires_alert = emergency or (distress and dominant_conf > 0.5) or safety_concern

        msg = TextEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.text"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)
        msg.text_snippet = text[:200]

        msg.dominant_emotion = dominant
        msg.dominant_confidence = float(dominant_conf)

        msg.emergency_detected = emergency
        msg.distress_detected = distress
        msg.medical_concern_detected = medical
        msg.safety_concern_detected = safety_concern
        msg.anger_detected = anger
        msg.confusion_detected = confusion

        msg.emergency_score = float(scores.get("emergency", 0.0))
        msg.distress_score = float(scores.get("distress", 0.0))
        msg.confusion_score = float(scores.get("confusion", 0.0))
        msg.anger_score = float(scores.get("anger", 0.0))
        msg.gratitude_score = float(scores.get("gratitude", 0.0))
        msg.complaint_score = float(scores.get("complaint", 0.0))
        msg.request_score = float(scores.get("request", 0.0))
        msg.medical_score = float(scores.get("medical", 0.0))
        msg.safety_score = float(scores.get("safety", 0.0))
        msg.neutral_score = float(scores.get("neutral", 0.0))

        msg.backend_used = self._backend_label
        msg.requires_operator_alert = requires_alert

        return msg

    def _make_suppressed_msg(self, person_id: str, tracking_id: int):
        """Build a TextEmotion message with all scores zeroed due to privacy.

        Args:
            person_id: String person identifier.
            tracking_id: Integer tracking ID.

        Returns:
            TextEmotion: Message with neutral dominant and zero scores.
        """
        from bonbon_msgs.msg import TextEmotion  # type: ignore[import]

        msg = TextEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.text"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)
        msg.text_snippet = ""
        msg.dominant_emotion = "neutral"
        msg.dominant_confidence = 0.0
        msg.backend_used = "suppressed"
        msg.requires_operator_alert = False
        return msg
