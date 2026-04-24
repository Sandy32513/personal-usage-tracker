from __future__ import annotations

import io
import json
import logging
import sqlite3
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.consolidate_logs as con
import scripts.data_integrity_check as dic
import scripts.generate_shifts_and_validate as gsv
import scripts.reset_runtime_data as rrd
import scripts.upload_logs as upl
import scripts.validate_db_setup as vdb
import src.observability as obs
import src.sqlserver_store as sqls


UTC = timezone.utc


def test_observability_module() -> None:
    formatter = obs.StructuredFormatter()
    record = logging.LogRecord(
        "usage_tracker",
        logging.INFO,
        __file__,
        10,
        "hello %s",
        ("world",),
        None,
        func="poller_step",
    )
    record.extra_fields = {"foo": "bar"}
    formatted = formatter.format(record)
    payload = json.loads(formatted)
    assert payload["message"] == "hello world"
    assert payload["component"] == "poller"
    assert payload["foo"] == "bar"

    logger = obs.EnterpriseLogger("audit_logger")
    logger.set_correlation_id("cid-123")
    logger.info("structured", stage="audit")
    logger.metric("jobs_total", 2, env="test")
    logger.trace("scan", 12.5, ok=True)
    logger.clear_correlation_id()

    metrics = obs.MetricsCollector()
    metrics.reset()
    metrics.counter("runs", {"env": "test"})
    metrics.gauge("queue_depth", 4.0)
    for value in range(1002):
        metrics.histogram("latency", float(value))
    output = metrics.get_metrics()
    assert "runs{env=test}" in output
    assert "queue_depth" in output
    assert "latency_count" in output
    assert len(metrics._histograms["latency"]) == 501

    @obs.measure_time("decorated")
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    tracker_logger = logging.getLogger("usage_tracker")
    tracker_logger.handlers = [handler]
    tracker_logger.setLevel(logging.INFO)
    obs.track_event("audit", status="ok")
    assert "event" in stream.getvalue()
    assert obs.create_correlation_id()


def test_sqlserver_store_connect_and_execute(monkeypatch) -> None:
    executed: list[tuple[str, tuple | None]] = []

    class FakeCursor:
        def __init__(self) -> None:
            self._result = None

        def execute(self, sql: str, params=None) -> None:
            executed.append((sql, params))
            self._result = None

        def fetchone(self):
            return self._result

        def close(self) -> None:
            return None

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False
            self.commit_calls = 0

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            self.closed = True

        def commit(self) -> None:
            self.commit_calls += 1

    connections: list[FakeConnection] = []

    def fake_connect(conn_str: str, timeout: int = 5, autocommit: bool = True):
        conn = FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setattr(sqls, "pyodbc", SimpleNamespace(connect=fake_connect))

    store = sqls.SQLServerStore(
        host="localhost",
        port=1433,
        user="sa",
        password="pw",
        database="tracker_db",
    )
    assert store.enabled is True
    assert "UID=sa;PWD=pw;" in store._get_connection_string(for_database=True)
    assert any("CREATE DATABASE" in sql for sql, _ in executed)

    windows_store = sqls.SQLServerStore(
        host="localhost",
        port=1433,
        user="WindowsAuth",
        password="",
        database="tracker_db",
    )
    assert "Trusted_Connection=yes;" in windows_store._get_connection_string(for_database=True)

    payload = {
        "started_at": datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 3, 17, 10, 1, tzinfo=UTC),
        "duration_seconds": 60,
        "process_name": "code.exe",
        "app_name": "VS Code",
        "window_title": "tracker",
        "browser": "chrome",
        "domain": "example.com",
        "url": "https://example.com",
        "page_title": "Example",
        "source": "active_window",
        "visited_at": datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
        "source_app": "spotify",
        "title": "Song",
        "artist": "Artist",
        "playback_state": "playing",
        "changed_at": datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
    }
    store.insert_app_usage(payload)
    store.insert_website_usage(payload)
    store.insert_website_visit(payload)
    store.insert_media_playback(payload)
    store.insert_media_track_change(payload)
    assert store.clear_all_usage_tables() is True
    assert store._calculate_shift_id(payload["ended_at"]) == 2
    store.close()

    unsafe = sqls.SQLServerStore(
        host="localhost",
        port=1433,
        user="sa",
        password="pw",
        database="bad;drop",
    )
    assert unsafe.enabled is False
    assert unsafe.disabled_reason is not None


def test_validate_db_setup_and_generate_scripts(monkeypatch, tmp_path: Path) -> None:
    vdb.MYSQL_AVAILABLE = False
    vdb.mysql = None
    assert vdb.test_database_connection("localhost", "root", "", "db") is False

    class FakeCursor:
        def __init__(self) -> None:
            self._fetch = [(1,)]

        def execute(self, sql: str) -> None:
            self._sql = sql

        def fetchone(self):
            return (1,)

        def close(self) -> None:
            return None

    class FakeConn:
        def cursor(self, **kwargs) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            return None

    vdb.MYSQL_AVAILABLE = True
    vdb.mysql = SimpleNamespace(connect=lambda **kwargs: FakeConn())
    monkeypatch.setenv("USAGE_TRACKER_MYSQL_HOST", "localhost")
    monkeypatch.setenv("USAGE_TRACKER_MYSQL_USER", "root")
    monkeypatch.setenv("USAGE_TRACKER_MYSQL_PASSWORD", "pw")
    monkeypatch.setenv("USAGE_TRACKER_MYSQL_DATABASE", "tracker")
    assert vdb.validate_db_credentials() is True

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        vdb.show_setup_instructions()
    assert "DATABASE SETUP INSTRUCTIONS" in buffer.getvalue()

    assert gsv._parse_bool(None) is False
    assert gsv._parse_bool("yes") is True

    class FakeDictCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql: str) -> None:
            self.last_sql = sql

        def fetchall(self):
            return [{"Tables_in_tracker": "app_usage"}]

        def fetchone(self):
            return {"cnt": 3}

        def close(self) -> None:
            return None

    class FakeDictConn:
        def cursor(self, **kwargs) -> FakeDictCursor:
            return FakeDictCursor()

        def close(self) -> None:
            return None

    gsv.MYSQL_AVAILABLE = True
    gsv.mysql = SimpleNamespace(connect=lambda **kwargs: FakeDictConn())
    result = gsv.validate_database("localhost", "root", "pw", "tracker")
    assert result["connected"] is True
    assert result["sample_app_usage_count"] == 3

    old_log = tmp_path / "usage_log_2026-03-01.txt"
    old_log.write_text("legacy", encoding="utf-8")
    cleanup = gsv.cleanup_old_logs(tmp_path, delete_old_files=True)
    assert cleanup["files_deleted"] == [old_log.name]

    class FakeEntry:
        def __init__(self, value: date) -> None:
            self.timestamp_local = datetime.combine(value, datetime.min.time(), tzinfo=UTC)

    class FakeMasterLog:
        def read_all(self):
            return [FakeEntry(date(2026, 3, 17))]

    class FakePipeline:
        def __init__(self) -> None:
            self.master_log = FakeMasterLog()

        def process_daily(self, target_date: date) -> dict[str, object]:
            return {
                "shift_csvs": [f"shift_{target_date}.csv"],
                "daily_csv": f"daily_{target_date}.csv",
                "workbook": f"daily_{target_date}.xlsx",
            }

        def process_weekly(self) -> dict[str, object]:
            return {"scheduled": True}

        def health_check(self) -> dict[str, object]:
            return {"ok": True}

        def close(self) -> None:
            return None

    fake_pipeline = FakePipeline()
    monkeypatch.setattr(gsv, "create_shift_manager", lambda **kwargs: fake_pipeline)
    monkeypatch.setattr(
        gsv,
        "validate_database",
        lambda *args, **kwargs: {"connected": False, "error": "not configured"},
    )
    monkeypatch.setattr(
        gsv,
        "__file__",
        str(tmp_path / "scripts" / "generate_shifts_and_validate.py"),
    )
    monkeypatch.chdir(tmp_path)
    gsv.main()
    assert (tmp_path / "consolidation_final_report.json").exists()


def test_upload_and_data_integrity_scripts(monkeypatch, tmp_path: Path) -> None:
    screenshot_dir = tmp_path / "screenshots"
    log_dir = tmp_path / "table_logs"
    dest_dir = tmp_path / "backups"
    db_path = tmp_path / "user_log.db"
    log_file = tmp_path / "user_log.txt"
    log_dir.mkdir()
    (log_dir / "app_usage.csv").write_text("x", encoding="utf-8")
    log_file.write_text("log", encoding="utf-8")
    db_path.write_text("db", encoding="utf-8")

    class FakeImage:
        def save(self, path: Path) -> None:
            path.write_text("img", encoding="utf-8")

    monkeypatch.setitem(__import__("sys").modules, "pyautogui", SimpleNamespace(screenshot=lambda: FakeImage()))
    image_path = upl.capture_screenshot(screenshot_dir)
    assert image_path is not None and image_path.exists()

    uploaded = upl.upload(log_dir, log_file, db_path, dest_dir, screenshot_dir)
    assert (uploaded / "app_usage.csv").exists()
    assert (uploaded / "user_log.db").exists()

    monkeypatch.setattr(upl, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(upl, "ensure_table_logs", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        upl.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            log_dir=str(log_dir),
            log_file=str(log_file),
            database_file=str(db_path),
            dest_dir=str(dest_dir),
            screenshot_dir=str(screenshot_dir),
        ),
    )
    upl.main()

    conn = sqlite3.connect(tmp_path / "integrity.db")
    conn.execute(
        """
        CREATE TABLE events (
            event_key TEXT,
            timestamp_local TEXT,
            shift_id INTEGER,
            event_type TEXT,
            category TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
        [
            ("dup", "2026-03-17T06:00:00+00:00", 3, "APP_USAGE", "APP"),
            ("dup", "2026-03-17T06:00:00+00:00", 3, "APP_USAGE", "APP"),
            ("visit", "2026-03-17T09:00:00+00:00", 1, "WEBSITE_VISIT", "WEB"),
        ],
    )
    conn.commit()
    conn.close()

    checker = dic.DataIntegrityChecker(tmp_path / "integrity.db")
    report = checker.check()
    assert report["status"] == "ISSUES"
    assert report["stats"]["duplicate_keys"] == 1
    assert report["stats"]["repaired"] == 3


def test_reset_runtime_and_consolidation_scripts(monkeypatch, tmp_path: Path) -> None:
    cutoff = date(2026, 3, 17)
    for folder_name, filename in [
        ("daily_csvs", "daily_log_2026-03-16.csv"),
        ("shift_csvs", "shift1_2026-03-16.csv"),
        ("reports", "daily_report_2026-03-16.txt"),
        ("weekly_archives", "weekly_2026-03-16"),
        ("backup_logs", "backup_2026-03-16"),
    ]:
        folder = tmp_path / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / filename
        if "." in filename:
            target.write_text("old", encoding="utf-8")
        else:
            target.mkdir(exist_ok=True)

    (tmp_path / "daily_log_2026-03-16.xlsx").write_text("old", encoding="utf-8")
    (tmp_path / "tracker.log").write_text("log", encoding="utf-8")
    (tmp_path / "user_log.db").write_text("db", encoding="utf-8")

    class FakePipeline:
        def prune_before(self, cutoff_local: datetime) -> dict[str, int]:
            return {
                "removed_log_entries": 2,
                "removed_events": 2,
                "remaining_events": 1,
            }

        def process_scheduled_tasks(self) -> dict[str, bool]:
            return {"ok": True}

        def close(self) -> None:
            return None

    monkeypatch.setattr(rrd, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rrd, "create_shift_manager", lambda *args, **kwargs: FakePipeline())
    monkeypatch.setattr(rrd, "ensure_table_logs", lambda *args, **kwargs: {"app_usage.csv": 1})
    summary = rrd.reset_runtime_data(cutoff)
    assert summary["prune_summary"]["removed_events"] == 2
    assert summary["filesystem_summary"]["rebuilt_table_log_files"] == 1

    monkeypatch.setattr(
        rrd.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(from_date="2026-03-17"),
    )
    rrd.main()

    class FakeAudit:
        def __init__(self, value: str) -> None:
            self.value = value

    class FakeConsolidationPipeline:
        def __init__(self) -> None:
            self.database = SimpleNamespace(
                all_entries=lambda: [
                    SimpleNamespace(timestamp_local=datetime(2026, 3, 17, tzinfo=UTC))
                ]
            )

        def generate_daily_workbook(self, value: date) -> Path:
            return tmp_path / f"{value}.xlsx"

        def analyze_existing_sources(self) -> FakeAudit:
            return FakeAudit("audit")

        def consolidate_legacy_logs(self, delete_old_files: bool = False) -> dict[str, bool]:
            return {"delete_old_files": delete_old_files}

        def process_weekly(self) -> dict[str, bool]:
            return {"scheduled": True}

        def health_check(self) -> dict[str, bool]:
            return {"ok": True}

    monkeypatch.setattr(con, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(con, "create_shift_manager", lambda **kwargs: FakeConsolidationPipeline())
    monkeypatch.setenv("USAGE_TRACKER_DELETE_OLD_FILES", "true")
    con.main()
    assert (tmp_path / "consolidation_report.json").exists()
