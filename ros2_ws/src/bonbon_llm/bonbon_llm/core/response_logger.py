"""
bonbon_llm.core.response_logger
================================
Structured, append-only log of every LLM request/response pair.

Every LLM interaction is recorded with:
  - full prompt (truncated to 2048 chars for storage)
  - raw LLM output
  - final filtered/personalised response
  - pipeline status (ok / safety_block / hallucination / low_confidence / llm_error)
  - hallucination flag
  - latency breakdown
  - list of tools called

In-process store: a fixed-size deque (default 1 000 entries) so memory
is bounded even in long deployments.  The ROS2 node additionally
publishes each entry as an LLMLog message for persistent external storage.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)

_MAX_TEXT_LEN = 2048  # chars stored per text field
_MAX_ENTRIES = 1_000  # in-memory log ring size


@dataclass
class LogEntry:
    response_id: str
    intent_id: str
    speaker_id: str
    timestamp: float

    # Content
    raw_prompt: str
    raw_llm_output: str
    final_response: str

    # Safety / hallucination outcome -- field names match LLMLog.msg exactly
    # (bonbon_msgs/msg/LLMLog.msg), since _publish_ros() assigns these
    # straight onto the ROS message.
    safety_filter_result: str
    safety_filter_reason: str
    hallucination_flagged: bool
    hallucination_reason: str

    # Timing
    llm_latency_ms: float
    rag_latency_ms: float
    total_latency_ms: float

    # RAG context
    rag_doc_ids: list[str] = field(default_factory=list)
    rag_scores: list[float] = field(default_factory=list)

    # Safety state snapshot
    safety_state: int = 0
    actuation_permitted: bool = True
    navigation_permitted: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class ResponseLogger:
    """
    Thread-safe, bounded in-memory log with optional ROS2 publisher sink.

    The ROS2 publisher is injected post-construction so the logger can
    be used in pure-Python tests without ROS2.
    """

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._log: deque[LogEntry] = deque(maxlen=max_entries)
        self._ros_publisher = None  # set via set_ros_publisher()

    def set_ros_publisher(self, publisher) -> None:
        """Inject a ROS2 publisher for /llm/log (set after node configure)."""
        self._ros_publisher = publisher

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(
        self,
        response_id: str,
        intent_id: str,
        speaker_id: str,
        raw_prompt: str,
        raw_llm_output: str,
        final_response: str,
        safety_filter_result: str = "SAFE",
        safety_filter_reason: str = "",
        hallucination_flagged: bool = False,
        hallucination_reason: str = "",
        llm_latency_ms: float = 0.0,
        rag_latency_ms: float = 0.0,
        total_latency_ms: float = 0.0,
        rag_doc_ids: list[str] | None = None,
        rag_scores: list[float] | None = None,
        safety_state: int = 0,
        actuation_permitted: bool = True,
        navigation_permitted: bool = True,
    ) -> str:
        """
        Record an LLM interaction and return response_id (echoed back).

        Parameters
        ----------
        response_id:           Caller-supplied ID shared with the published
                                LLMResponse, so both messages correlate.
        intent_id:              Identifier for the intent / request.
        speaker_id:              Anonymous speaker identifier.
        raw_prompt:              Original user utterance (truncated to 2048 chars).
        raw_llm_output:          Raw LLM output before filtering.
        final_response:          Final response sent to TTS.
        safety_filter_result:    "SAFE" | "RISKY" | "BLOCKED".
        safety_filter_reason:    Why a command was blocked or flagged.
        hallucination_flagged:   True if the hallucination guard fired.
        hallucination_reason:    Why the hallucination guard fired.
        llm_latency_ms:          Time spent waiting for the LLM (ms).
        rag_latency_ms:          Time spent on RAG retrieval (ms).
        total_latency_ms:        End-to-end pipeline latency (ms).
        rag_doc_ids:             IDs of retrieved RAG documents.
        rag_scores:              Similarity scores for retrieved documents.
        safety_state:            SafetyState.state_id at time of request.
        actuation_permitted:     Whether actuation was permitted at request time.
        navigation_permitted:    Whether navigation was permitted at request time.
        """
        entry = LogEntry(
            response_id=response_id,
            intent_id=intent_id,
            speaker_id=speaker_id,
            timestamp=time.time(),
            raw_prompt=raw_prompt[:_MAX_TEXT_LEN],
            raw_llm_output=raw_llm_output[:_MAX_TEXT_LEN],
            final_response=final_response[:_MAX_TEXT_LEN],
            safety_filter_result=safety_filter_result,
            safety_filter_reason=safety_filter_reason,
            hallucination_flagged=hallucination_flagged,
            hallucination_reason=hallucination_reason,
            llm_latency_ms=llm_latency_ms,
            rag_latency_ms=rag_latency_ms,
            total_latency_ms=total_latency_ms,
            rag_doc_ids=list(rag_doc_ids) if rag_doc_ids else [],
            rag_scores=list(rag_scores) if rag_scores else [],
            safety_state=safety_state,
            actuation_permitted=actuation_permitted,
            navigation_permitted=navigation_permitted,
        )
        self._log.append(entry)
        logger.debug(
            "LLM log [%s] safety=%s hallucination=%s latency=%.1fms",
            response_id[:8],
            safety_filter_result,
            hallucination_flagged,
            total_latency_ms,
        )
        self._publish_ros(entry)
        return response_id

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_recent(self, n: int = 10) -> list[LogEntry]:
        entries = list(self._log)
        return entries[-n:]

    def get_by_id(self, response_id: str) -> LogEntry | None:
        for entry in reversed(self._log):
            if entry.response_id == response_id:
                return entry
        return None

    def clear_log(self) -> None:
        """Empty the in-memory log (does not affect ROS2 sink)."""
        self._log.clear()

    @property
    def entry_count(self) -> int:
        return len(self._log)

    # ── ROS2 sink ─────────────────────────────────────────────────────────────

    def _publish_ros(self, entry: LogEntry) -> None:
        if self._ros_publisher is None:
            return
        try:
            from bonbon_msgs.msg import LLMLog  # type: ignore

            msg = LLMLog()
            msg.log_id = str(uuid.uuid4())
            msg.response_id = entry.response_id
            msg.intent_id = entry.intent_id
            msg.speaker_id = entry.speaker_id
            msg.llm_latency_ms = float(entry.llm_latency_ms)
            msg.rag_latency_ms = float(entry.rag_latency_ms)
            msg.total_latency_ms = float(entry.total_latency_ms)
            msg.raw_prompt = entry.raw_prompt
            msg.raw_llm_output = entry.raw_llm_output
            msg.final_response = entry.final_response
            msg.safety_filter_result = entry.safety_filter_result
            msg.safety_filter_reason = entry.safety_filter_reason
            msg.hallucination_flagged = entry.hallucination_flagged
            msg.hallucination_reason = entry.hallucination_reason
            msg.rag_doc_ids = list(entry.rag_doc_ids)
            msg.rag_scores = [float(s) for s in entry.rag_scores]
            msg.safety_state = int(entry.safety_state)
            msg.actuation_permitted = entry.actuation_permitted
            msg.navigation_permitted = entry.navigation_permitted
            self._ros_publisher.publish(msg)
        except Exception as exc:
            logger.debug("LLMLog publish error (non-fatal): %s", exc)
