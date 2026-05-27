"""
tests.test_response_logger
===========================
Unit tests for bonbon_llm.core.response_logger.ResponseLogger.

Tests cover
-----------
* record() adds entries to the log
* get_recent(n) returns the n most recent entries
* get_by_id() returns the correct entry
* Bounded deque (max_entries) discards oldest entries
* clear_log() empties the log
* LogEntry fields are populated correctly
* No ROS2 publisher injected → works standalone
"""

import time

import pytest
from bonbon_llm.core.response_logger import LogEntry, ResponseLogger

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def logger() -> ResponseLogger:
    return ResponseLogger(max_entries=100)


def _record(
    log: ResponseLogger,
    intent_id: str = "intent_001",
    speaker_id: str = "spk_01",
    raw_prompt: str = "User asked about latte.",
    raw_llm_output: str = "The latte is S$5.00.",
    final_response: str = "The latte is S$5.00.",
    status: str = "ok",
    confidence: float = 0.90,
    llm_latency_ms: float = 120.0,
    rag_latency_ms: float = 5.0,
    tools_called: list = None,
    hallucination_flagged: bool = False,
) -> str:
    return log.record(
        intent_id=intent_id,
        speaker_id=speaker_id,
        raw_prompt=raw_prompt,
        raw_llm_output=raw_llm_output,
        final_response=final_response,
        status=status,
        confidence=confidence,
        llm_latency_ms=llm_latency_ms,
        rag_latency_ms=rag_latency_ms,
        tools_called=tools_called or [],
        hallucination_flagged=hallucination_flagged,
    )


# ── Basic record/retrieve ──────────────────────────────────────────────────────


class TestRecordAndRetrieve:

    def test_record_returns_response_id(self, logger):
        rid = _record(logger)
        assert isinstance(rid, str)
        assert len(rid) > 0

    def test_record_increments_log_size(self, logger):
        assert len(logger.get_recent(100)) == 0
        _record(logger)
        assert len(logger.get_recent(100)) == 1
        _record(logger)
        assert len(logger.get_recent(100)) == 2

    def test_get_recent_returns_most_recent_first(self, logger):
        [_record(logger, intent_id=f"intent_{i}") for i in range(5)]
        recent = logger.get_recent(3)
        # Most recent should be last-recorded
        assert len(recent) == 3

    def test_get_by_id_returns_correct_entry(self, logger):
        rid = _record(logger, final_response="Unique response XZY")
        entry = logger.get_by_id(rid)
        assert entry is not None
        assert entry.response_id == rid
        assert entry.final_response == "Unique response XZY"

    def test_get_by_id_missing_returns_none(self, logger):
        assert logger.get_by_id("nonexistent_id_9999") is None

    def test_get_recent_returns_list(self, logger):
        _record(logger)
        result = logger.get_recent(5)
        assert isinstance(result, list)

    def test_get_recent_respects_n(self, logger):
        for _ in range(10):
            _record(logger)
        recent = logger.get_recent(3)
        assert len(recent) == 3


# ── LogEntry field population ─────────────────────────────────────────────────


class TestLogEntryFields:

    def test_intent_id_stored(self, logger):
        rid = _record(logger, intent_id="test_intent_42")
        entry = logger.get_by_id(rid)
        assert entry.intent_id == "test_intent_42"

    def test_speaker_id_stored(self, logger):
        rid = _record(logger, speaker_id="anon_abc123")
        entry = logger.get_by_id(rid)
        assert entry.speaker_id == "anon_abc123"

    def test_confidence_stored(self, logger):
        rid = _record(logger, confidence=0.73)
        entry = logger.get_by_id(rid)
        assert abs(entry.confidence - 0.73) < 1e-4

    def test_status_stored(self, logger):
        rid = _record(logger, status="safety_block")
        entry = logger.get_by_id(rid)
        assert entry.status == "safety_block"

    def test_latency_stored(self, logger):
        rid = _record(logger, llm_latency_ms=250.0, rag_latency_ms=12.0)
        entry = logger.get_by_id(rid)
        assert abs(entry.llm_latency_ms - 250.0) < 1.0
        assert abs(entry.rag_latency_ms - 12.0) < 1.0

    def test_hallucination_flag_stored(self, logger):
        rid = _record(logger, hallucination_flagged=True)
        entry = logger.get_by_id(rid)
        assert entry.hallucination_flagged is True

    def test_tools_called_stored(self, logger):
        rid = _record(logger, tools_called=["speak_to_user", "get_menu_info"])
        entry = logger.get_by_id(rid)
        assert "speak_to_user" in entry.tools_called
        assert "get_menu_info" in entry.tools_called

    def test_timestamp_is_recent(self, logger):
        before = time.time()
        rid = _record(logger)
        after = time.time()
        entry = logger.get_by_id(rid)
        assert before <= entry.timestamp <= after

    def test_response_id_unique(self, logger):
        ids = [_record(logger) for _ in range(20)]
        assert len(set(ids)) == 20, "All response IDs should be unique"


# ── Bounded deque ─────────────────────────────────────────────────────────────


class TestBoundedDeque:

    def test_max_entries_enforced(self):
        log = ResponseLogger(max_entries=5)
        [_record(log, intent_id=f"intent_{i}") for i in range(10)]
        # Only 5 most recent should be retained
        assert len(log.get_recent(100)) == 5

    def test_oldest_entries_discarded(self):
        log = ResponseLogger(max_entries=3)
        _record(log, intent_id="old_one", final_response="Response 1")
        _record(log, intent_id="old_two", final_response="Response 2")
        _record(log, intent_id="old_three", final_response="Response 3")
        _record(log, intent_id="new_one", final_response="Response 4")
        # old_one should be gone
        all_entries = log.get_recent(100)
        intents = [e.intent_id for e in all_entries]
        assert "old_one" not in intents
        assert "new_one" in intents


# ── clear_log ─────────────────────────────────────────────────────────────────


class TestClearLog:

    def test_clear_empties_log(self, logger):
        _record(logger)
        _record(logger)
        logger.clear_log()
        assert len(logger.get_recent(100)) == 0

    def test_clear_then_record_works(self, logger):
        _record(logger)
        logger.clear_log()
        rid = _record(logger, final_response="After clear")
        entry = logger.get_by_id(rid)
        assert entry is not None
        assert entry.final_response == "After clear"


# ── No ROS2 publisher ─────────────────────────────────────────────────────────


class TestNoPublisher:

    def test_works_without_publisher(self):
        log = ResponseLogger(max_entries=50)
        # No publisher set — should not raise
        rid = _record(log)
        assert rid is not None

    def test_set_publisher_to_none_does_not_crash(self, logger):
        logger.set_ros_publisher(None)
        rid = _record(logger)
        assert rid is not None


# ── LogEntry dataclass ────────────────────────────────────────────────────────


class TestLogEntryDataclass:

    def test_log_entry_is_dataclass(self, logger):
        rid = _record(logger)
        entry = logger.get_by_id(rid)
        assert isinstance(entry, LogEntry)

    def test_log_entry_repr_does_not_crash(self, logger):
        rid = _record(logger)
        entry = logger.get_by_id(rid)
        _ = repr(entry)  # should not raise
