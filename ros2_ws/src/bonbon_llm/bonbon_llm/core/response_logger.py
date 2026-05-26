"""
bonbon_llm.core.response_logger
================================
Structured, append-only log of every LLM request/response pair.

Every LLM interaction is recorded with:
  - full prompt (truncated to 2048 chars for storage)
  - raw LLM output
  - final filtered/personalised response
  - safety decision
  - hallucination flag
  - latency breakdown
  - safety state snapshot at time of request

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
from typing import Deque, List, Optional

logger = logging.getLogger(__name__)

_MAX_TEXT_LEN = 2048    # chars stored per text field
_MAX_ENTRIES  = 1_000   # in-memory log ring size


@dataclass
class LogEntry:
    log_id:              str
    response_id:         str
    intent_id:           str
    speaker_id:          str
    timestamp:           float

    # Timing
    llm_latency_ms:      float
    rag_latency_ms:      float
    total_latency_ms:    float

    # Content
    raw_prompt:          str
    raw_llm_output:      str
    final_response:      str

    # Safety
    safety_filter_result:str     # "SAFE" | "RISKY" | "BLOCKED"
    safety_filter_reason:str
    hallucination_flagged:bool
    hallucination_reason: str

    # RAG
    rag_doc_ids:         List[str] = field(default_factory=list)
    rag_scores:          List[float] = field(default_factory=list)

    # Safety state snapshot
    safety_state:        int   = 0
    actuation_permitted: bool  = True
    navigation_permitted:bool  = True

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
        self._log: Deque[LogEntry] = deque(maxlen=max_entries)
        self._ros_publisher = None   # set via set_ros_publisher()

    def set_ros_publisher(self, publisher) -> None:
        """Inject a ROS2 publisher for /llm/log (set after node configure)."""
        self._ros_publisher = publisher

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(
        self,
        response_id:          str,
        intent_id:            str,
        speaker_id:           str,
        raw_prompt:           str,
        raw_llm_output:       str,
        final_response:       str,
        safety_filter_result: str,
        safety_filter_reason: str,
        hallucination_flagged:bool,
        hallucination_reason: str,
        llm_latency_ms:       float,
        rag_latency_ms:       float,
        total_latency_ms:     float,
        rag_doc_ids:          Optional[List[str]] = None,
        rag_scores:           Optional[List[float]] = None,
        safety_state:         int   = 0,
        actuation_permitted:  bool  = True,
        navigation_permitted: bool  = True,
    ) -> LogEntry:
        entry = LogEntry(
            log_id               = str(uuid.uuid4()),
            response_id          = response_id,
            intent_id            = intent_id,
            speaker_id           = speaker_id,
            timestamp            = time.time(),
            llm_latency_ms       = llm_latency_ms,
            rag_latency_ms       = rag_latency_ms,
            total_latency_ms     = total_latency_ms,
            raw_prompt           = raw_prompt[:_MAX_TEXT_LEN],
            raw_llm_output       = raw_llm_output[:_MAX_TEXT_LEN],
            final_response       = final_response[:_MAX_TEXT_LEN],
            safety_filter_result = safety_filter_result,
            safety_filter_reason = safety_filter_reason,
            hallucination_flagged= hallucination_flagged,
            hallucination_reason = hallucination_reason,
            rag_doc_ids          = rag_doc_ids or [],
            rag_scores           = rag_scores or [],
            safety_state         = safety_state,
            actuation_permitted  = actuation_permitted,
            navigation_permitted = navigation_permitted,
        )
        self._log.append(entry)
        logger.debug("LLM log [%s] safety=%s hallucination=%s latency=%.1fms",
                     entry.log_id[:8], safety_filter_result,
                     hallucination_flagged, total_latency_ms)
        self._publish_ros(entry)
        return entry

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_recent(self, n: int = 10) -> List[LogEntry]:
        entries = list(self._log)
        return entries[-n:]

    def get_by_id(self, response_id: str) -> Optional[LogEntry]:
        for entry in reversed(self._log):
            if entry.response_id == response_id:
                return entry
        return None

    @property
    def entry_count(self) -> int:
        return len(self._log)

    # ── ROS2 sink ─────────────────────────────────────────────────────────────

    def _publish_ros(self, entry: LogEntry) -> None:
        if self._ros_publisher is None:
            return
        try:
            from bonbon_msgs.msg import LLMLog  # type: ignore
            from std_msgs.msg import Header      # type: ignore
            import rclpy.time                    # type: ignore
            msg = LLMLog()
            msg.log_id              = entry.log_id
            msg.response_id         = entry.response_id
            msg.intent_id           = entry.intent_id
            msg.speaker_id          = entry.speaker_id
            msg.llm_latency_ms      = float(entry.llm_latency_ms)
            msg.rag_latency_ms      = float(entry.rag_latency_ms)
            msg.total_latency_ms    = float(entry.total_latency_ms)
            msg.raw_prompt          = entry.raw_prompt
            msg.raw_llm_output      = entry.raw_llm_output
            msg.final_response      = entry.final_response
            msg.safety_filter_result= entry.safety_filter_result
            msg.safety_filter_reason= entry.safety_filter_reason
            msg.hallucination_flagged=entry.hallucination_flagged
            msg.hallucination_reason= entry.hallucination_reason
            msg.rag_doc_ids         = list(entry.rag_doc_ids)
            msg.rag_scores          = [float(s) for s in entry.rag_scores]
            msg.safety_state        = entry.safety_state
            msg.actuation_permitted = entry.actuation_permitted
            msg.navigation_permitted= entry.navigation_permitted
            self._ros_publisher.publish(msg)
        except Exception as exc:
            logger.debug("LLMLog publish error (non-fatal): %s", exc)
