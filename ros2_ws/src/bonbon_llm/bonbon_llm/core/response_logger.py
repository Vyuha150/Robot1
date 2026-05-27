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

    # Pipeline outcome
    status: str  # "ok" | "safety_block" | "hallucination" | "low_confidence" | "llm_error"
    confidence: float  # LLM self-reported confidence 0–1
    hallucination_flagged: bool

    # Timing
    llm_latency_ms: float
    rag_latency_ms: float

    # Tools
    tools_called: list[str] = field(default_factory=list)

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
        intent_id: str,
        speaker_id: str,
        raw_prompt: str,
        raw_llm_output: str,
        final_response: str,
        status: str = "ok",
        confidence: float = 1.0,
        llm_latency_ms: float = 0.0,
        rag_latency_ms: float = 0.0,
        tools_called: list[str] | None = None,
        hallucination_flagged: bool = False,
    ) -> str:
        """
        Record an LLM interaction and return the auto-generated response_id.

        Parameters
        ----------
        intent_id:            Identifier for the intent / request.
        speaker_id:           Anonymous speaker identifier.
        raw_prompt:           Original user utterance (truncated to 2048 chars).
        raw_llm_output:       Raw LLM output before filtering.
        final_response:       Final response sent to TTS.
        status:               Pipeline outcome string.
        confidence:           LLM self-reported confidence (0–1).
        llm_latency_ms:       Time spent waiting for the LLM (ms).
        rag_latency_ms:       Time spent on RAG retrieval (ms).
        tools_called:         List of tool names invoked during this turn.
        hallucination_flagged:True if the hallucination guard fired.
        """
        response_id = str(uuid.uuid4())
        entry = LogEntry(
            response_id=response_id,
            intent_id=intent_id,
            speaker_id=speaker_id,
            timestamp=time.time(),
            raw_prompt=raw_prompt[:_MAX_TEXT_LEN],
            raw_llm_output=raw_llm_output[:_MAX_TEXT_LEN],
            final_response=final_response[:_MAX_TEXT_LEN],
            status=status,
            confidence=confidence,
            hallucination_flagged=hallucination_flagged,
            llm_latency_ms=llm_latency_ms,
            rag_latency_ms=rag_latency_ms,
            tools_called=list(tools_called) if tools_called else [],
        )
        self._log.append(entry)
        logger.debug(
            "LLM log [%s] status=%s hallucination=%s latency=%.1fms",
            response_id[:8],
            status,
            hallucination_flagged,
            llm_latency_ms,
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
            msg.response_id = entry.response_id
            msg.intent_id = entry.intent_id
            msg.speaker_id = entry.speaker_id
            msg.raw_prompt = entry.raw_prompt
            msg.raw_llm_output = entry.raw_llm_output
            msg.final_response = entry.final_response
            msg.status = entry.status
            msg.confidence = float(entry.confidence)
            msg.llm_latency_ms = float(entry.llm_latency_ms)
            msg.rag_latency_ms = float(entry.rag_latency_ms)
            msg.hallucination_flagged = entry.hallucination_flagged
            msg.tools_called = list(entry.tools_called)
            self._ros_publisher.publish(msg)
        except Exception as exc:
            logger.debug("LLMLog publish error (non-fatal): %s", exc)
