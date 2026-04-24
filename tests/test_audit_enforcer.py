from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.audit_enforcer as ae


UTC = timezone.utc


def test_audit_event_creation() -> None:
    event = ae.AuditEvent(
        timestamp=ae.utc_now(),
        operation="INSERT",
        table_name="events",
        db_name="test.db",
        query="INSERT INTO events VALUES (?, ?, ?)",
        params=("key1", "data1", "data2"),
        result="SUCCESS",
        row_count=1,
        duration_ms=10.5,
    )
    assert event.operation == "INSERT"
    assert event.result == "SUCCESS"
    assert event.row_count == 1


def test_audit_logger_file(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.log"
    logger = ae.AuditLogger(audit_file)
    
    event = ae.AuditEvent(
        timestamp=ae.utc_now(),
        operation="INSERT",
        table_name="test",
        db_name="test.db",
        query="SELECT 1",
        params=(),
        result="SUCCESS",
    )
    
    logger.log(event)
    assert audit_file.exists()
    
    with audit_file.open("r") as f:
        line = f.readline()
        data = json.loads(line)
        assert data["operation"] == "INSERT"


def test_strict_audit_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    
    strict_db = ae.StrictAuditDB(conn, "test.db", strict=True)
    
    strict_db.execute("INSERT INTO items (name) VALUES (?)", ("test_item",))
    conn.commit()
    
    cursor = conn.execute("SELECT COUNT(*) FROM items")
    assert cursor.fetchone()[0] == 1
    
    conn.close()


def test_strict_audit_db_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    
    strict_db = ae.StrictAuditDB(conn, "test.db", strict=True)
    
    with pytest.raises(RuntimeError, match="AUDIT ENFORCEMENT FAILED"):
        strict_db.execute("INSERT INTO nonexistent_table VALUES (1)", ())
    
    conn.close()


def test_audit_verifier(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.log"
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute("CREATE TABLE events (event_key TEXT PRIMARY KEY, data TEXT)")
    conn.commit()
    
    audit = ae.AuditLogger(audit_file)
    verifier = ae.AuditVerifier(audit)
    
    result = verifier.verify_all_tables(conn)
    assert "status" in result
    assert "tables" in result
    
    conn.close()


def test_manual_trigger(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute("CREATE TABLE events (event_key TEXT PRIMARY KEY, data TEXT)")
    conn.commit()
    
    manual = ae.ManualTrigger()
    result = manual.trigger_audit_check(conn, "test.db")
    assert "status" in result
    
    conn.close()


def test_audited_execute_function(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    
    ae.audited_execute(conn, "INSERT INTO items (name) VALUES (?)", ("test",), "test.db")
    
    cursor = conn.execute("SELECT COUNT(*) FROM items")
    assert cursor.fetchone()[0] == 1
    
    conn.close()


def test_audited_execute_strict_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    
    with pytest.raises(RuntimeError, match="AUDIT ENFORCEMENT FAILED"):
        ae.audited_execute(conn, "INSERT INTO nonexistent VALUES (1)", (), "test.db", strict=True)
    
    conn.close()


def test_extract_table() -> None:
    strict_db = ae.StrictAuditDB(None, "test", strict=False)
    assert strict_db._extract_table("INSERT INTO events VALUES (1, 2)") == "events"
    assert strict_db._extract_table("SELECT * FROM items WHERE id = 1") == "items"
    assert strict_db._extract_table("DELETE FROM logs WHERE id > 10") == "logs"
    assert strict_db._extract_table("UPDATE users SET name = 'test'") == "users"


def test_batch_execution(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    
    strict_db = ae.StrictAuditDB(conn, "test.db", strict=True)
    strict_db.executemany(
        "INSERT INTO items (name) VALUES (?)",
        [("item1",), ("item2",), ("item3",)]
    )
    
    cursor = conn.execute("SELECT COUNT(*) FROM items")
    assert cursor.fetchone()[0] == 3
    
    conn.close()


def test_audit_sqlite_trigger_generation() -> None:
    strict_db = ae.StrictAuditDB(None, "test", strict=False)
    sql = strict_db.create_audit_trigger_sqlite("events")
    assert "events_audit" in sql
    assert "operation" in sql


def test_read_audit_log(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.log"
    logger = ae.AuditLogger(audit_file)
    
    events = [
        ae.AuditEvent(
            timestamp=ae.utc_now(),
            operation="INSERT",
            table_name="test",
            db_name="test.db",
            query="SELECT 1",
            params=(),
            result="SUCCESS",
        )
        for _ in range(5)
    ]
    logger.log_batch(events)
    
    read_events = logger.read_audit_log()
    assert len(read_events) == 5


def test_audited_execute_fetch(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('a'), ('b'), ('c')")
    conn.commit()
    
    results = ae.audited_execute_fetch(conn, "SELECT * FROM items", db_name="test.db")
    assert len(results) == 3
    
    conn.close()