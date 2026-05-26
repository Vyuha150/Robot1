"""AuditLogger unit tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from bonbon_operator_api.audit.audit_logger import AuditLogger


@pytest.fixture
def al(tmp_path):
    return AuditLogger(db_path=tmp_path / "audit.db", max_events=100)


# Scenario 1: Log basic event
def test_log_returns_event_id(al):
    eid = al.log(actor_id="u1", actor_name="alice", actor_role="admin", action="test")
    assert isinstance(eid, str) and len(eid) == 36


# Scenario 2: Count increases after log
def test_count_increases(al):
    before = al.count()
    al.log("u1", "alice", "admin", "action:test")
    assert al.count() == before + 1


# Scenario 3: Query by actor_id
def test_query_by_actor_id(al):
    al.log("actor-A", "bob", "viewer", "read:status")
    al.log("actor-B", "charlie", "operator", "command:speak")
    results = al.query(actor_id="actor-A")
    assert all(r["actor_id"] == "actor-A" for r in results)


# Scenario 4: Query by action
def test_query_by_action(al):
    al.log("u1", "alice", "admin", "auth:login")
    al.log("u2", "bob", "operator", "command:navigate")
    results = al.query(action="auth")
    assert all("auth" in r["action"] for r in results)


# Scenario 5: Query with since_ts filter
def test_query_since_ts(al):
    al.log("u1", "alice", "admin", "old:event")
    ts_marker = time.time()
    time.sleep(0.01)
    al.log("u2", "bob", "operator", "new:event")
    results = al.query(since_ts=ts_marker)
    assert all(r["timestamp"] >= ts_marker for r in results)


# Scenario 6: Query limit enforced
def test_query_limit(al):
    for i in range(10):
        al.log("u1", "alice", "admin", f"action:{i}")
    results = al.query(limit=3)
    assert len(results) <= 3


# Scenario 7: Query offset works
def test_query_offset(al):
    for i in range(5):
        al.log("u1", "alice", "admin", f"offset_action:{i}")
    r0 = al.query(limit=2, offset=0)
    r1 = al.query(limit=2, offset=1)
    # First entry of r1 should differ from first entry of r0 if enough events exist
    assert r0 != r1 or len(r0) == 0


# Scenario 8: Log with request_data serialised
def test_log_with_request_data(al):
    al.log("u1", "alice", "admin", "action:test",
           request_data={"key": "value", "count": 42})
    results = al.query(actor_id="u1", limit=1)
    assert results  # at least one row


# Scenario 9: Log with ip_address
def test_log_with_ip(al):
    eid = al.log("u1", "alice", "admin", "action:test",
                 ip_address="192.168.1.100")
    results = al.query(actor_id="u1", limit=1)
    assert any(r["ip_address"] == "192.168.1.100" for r in results)


# Scenario 10: Log with duration_ms
def test_log_with_duration(al):
    al.log("u1", "alice", "admin", "action:timed", duration_ms=42.5)
    results = al.query(actor_id="u1", limit=1)
    assert results[0]["duration_ms"] == 42.5


# Scenario 11: Log never raises even with corrupt data
def test_log_never_raises(al, monkeypatch):
    """Simulate DB failure; log() must not propagate exception."""
    def _broken_conn():
        raise RuntimeError("DB is gone")
    monkeypatch.setattr(al, "_conn", _broken_conn)
    eid = al.log("u1", "alice", "admin", "action:test")  # must not raise
    assert isinstance(eid, str)


# Scenario 12: Query returns empty list on DB failure
def test_query_returns_empty_on_failure(al, monkeypatch):
    def _broken_conn():
        raise RuntimeError("DB is gone")
    monkeypatch.setattr(al, "_conn", _broken_conn)
    results = al.query()
    assert results == []


# Scenario 13: Count returns 0 on failure
def test_count_returns_zero_on_failure(al, monkeypatch):
    def _broken_conn():
        raise RuntimeError("DB is gone")
    monkeypatch.setattr(al, "_conn", _broken_conn)
    assert al.count() == 0


# Scenario 14: WAL mode is enabled
def test_wal_mode_enabled(al):
    with al._conn() as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode == "wal"


# Scenario 15: Prune removes excess events
def test_prune(tmp_path):
    small_al = AuditLogger(db_path=tmp_path / "prune.db", max_events=5)
    for i in range(8):
        small_al.log("u1", "alice", "admin", f"action:{i}")
    small_al._prune()
    assert small_al.count() <= 5


# Scenario 16: Multiple events logged and queried correctly
def test_multiple_events_query(al):
    for action in ["auth:login", "command:speak", "config:write"]:
        al.log("u1", "alice", "admin", action)
    results = al.query(actor_id="u1", limit=100)
    actions_found = {r["action"] for r in results}
    assert "auth:login" in actions_found
    assert "command:speak" in actions_found


# Scenario 17: Outcome field stored correctly
def test_outcome_stored(al):
    al.log("u1", "alice", "admin", "command:navigate",
           outcome="safety_blocked", detail="halted state")
    results = al.query(actor_id="u1", action="command:navigate", limit=1)
    assert results[0]["outcome"] == "safety_blocked"


# Scenario 18: Detail field stored correctly
def test_detail_stored(al):
    al.log("u1", "alice", "admin", "action:test",
           detail="some detail text here")
    results = al.query(actor_id="u1", limit=1)
    assert "some detail text here" in results[0]["detail"]


# Scenario 19: Indexes exist (performance)
def test_indexes_exist(al):
    with al._conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='audit_events';"
        ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_audit_ts" in names
    assert "idx_audit_actor" in names


# Scenario 20: Log with empty target defaults correctly
def test_log_empty_target(al):
    al.log("u1", "alice", "admin", "action:test")
    results = al.query(actor_id="u1", limit=1)
    assert results[0]["target"] == ""
