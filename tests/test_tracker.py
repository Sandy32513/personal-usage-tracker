from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import usage_tracker as ut


UTC = timezone.utc


class DummyStore:
    def __init__(self) -> None:
        self.events = []

    def write(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))

    def write_app_usage(self, payload: dict) -> None:
        self.events.append(("APP_USAGE_CSV", payload))

    def write_website_usage(self, payload: dict) -> None:
        self.events.append(("WEBSITE_USAGE_CSV", payload))

    def write_website_visit(self, payload: dict) -> None:
        self.events.append(("WEBSITE_VISIT_CSV", payload))


class DummyMySQL:
    def __init__(self) -> None:
        self.app_usage = []
        self.website_usage = []
        self.website_visit = []
        self.enabled = False
        self.disabled_reason = "disabled"

    def insert_app_usage(self, payload: dict) -> None:
        self.app_usage.append(payload)

    def insert_website_usage(self, payload: dict) -> None:
        self.website_usage.append(payload)

    def insert_website_visit(self, payload: dict) -> None:
        self.website_visit.append(payload)

    def clear_all_usage_tables(self) -> bool:
        return True

    def close(self) -> None:
        return None


@pytest.fixture
def tracker(monkeypatch) -> ut.UsageTracker:
    config = ut.TrackerConfig(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="",
        mysql_database="test",
        log_file=ut.Path("usage_log.txt"),
        table_log_dir=ut.Path("table_logs"),
        state_file=ut.Path("tracker_state.json"),
        poll_interval=1.0,
        history_poll_interval=5.0,
        weekly_reset_enabled=False,
        weekly_reset_weekday=0,
        weekly_reset_hour=0,
        weekly_reset_minute=0,
        archive_log_on_weekly_reset=True,
        weekly_archive_dir=ut.Path("weekly_archives"),
        weekly_archive_clear_csv=False,
        quiet=True,
    )

    tr = ut.UsageTracker(config)
    tr.local_store = DummyStore()
    tr.table_store = DummyStore()
    tr.mysql_store = DummyMySQL()
    tr.history_poller = MagicMock()
    tr.history_poller.poll.return_value = []
    tr.history_poller.infer_active_url.return_value = (None, None, None)
    tr.history_poller.infer_session_url.return_value = (None, None, None)
    tr.media_poller = MagicMock()
    return tr


def test_session_start_end(tracker: ut.UsageTracker) -> None:
    now = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    window_a = {
        "process_name": "chrome.exe",
        "app_name": "chrome",
        "window_title": "Google Chrome",
    }
    tracker._start_session(window_a, now)
    assert tracker.current_session is not None
    tracker._flush_session(now + timedelta(seconds=10))
    assert tracker.current_session is None
    assert tracker.mysql_store.app_usage


def test_grace_window_prevents_split(tracker: ut.UsageTracker) -> None:
    now = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    window_a = {
        "process_name": "notepad.exe",
        "app_name": "notepad",
        "window_title": "Untitled - Notepad",
    }
    tracker._start_session(window_a, now)
    tracker.last_window_seen = now
    tracker._handle_window(None, now + timedelta(seconds=1))
    assert tracker.current_session is not None
    tracker._handle_window(None, now + timedelta(seconds=5))
    assert tracker.current_session is None


def test_poll_interval_respected(tracker: ut.UsageTracker, monkeypatch) -> None:
    wait_calls = []

    def fake_wait(value: float) -> None:
        wait_calls.append(value)

    tracker.stop_event.wait = fake_wait
    tracker._get_foreground_window = MagicMock(return_value=None)
    tracker.run_cycle()
    assert wait_calls
    assert wait_calls[-1] == tracker.config.poll_interval


def test_runtime_wires_real_table_and_mysql_stores(
    tmp_path, monkeypatch
) -> None:
    def fake_connect(self) -> None:
        self.enabled = False
        self.disabled_reason = "disabled for unit test"
        self.conn = None

    monkeypatch.setattr(ut.MySQLStore, "_connect", fake_connect)

    config = ut.TrackerConfig(
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="",
        mysql_database="test",
        log_file=tmp_path / "user_log.txt",
        table_log_dir=tmp_path / "table_logs",
        state_file=tmp_path / "tracker_state.json",
        poll_interval=1.0,
        history_poll_interval=5.0,
        weekly_reset_enabled=False,
        weekly_reset_weekday=0,
        weekly_reset_hour=0,
        weekly_reset_minute=0,
        archive_log_on_weekly_reset=True,
        weekly_archive_dir=tmp_path / "weekly_archives",
        weekly_archive_clear_csv=False,
        quiet=True,
    )

    tracker = ut.UsageTracker(config)
    try:
        assert isinstance(tracker.table_store, ut.LocalTableStore)
        assert isinstance(tracker.mysql_store, ut.MySQLStore)
        assert tracker.shift_manager is None
    finally:
        tracker.request_stop("unit_test")
        tracker._finalize()


def test_mysql_schema_helpers_only_apply_missing_changes() -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.columns = {("app_usage", "shift_id")}
            self.indexes = {("app_usage", "idx_app_shift")}
            self.executed: list[tuple[str, tuple | None]] = []
            self._last_result = None

        def execute(self, sql: str, params=None) -> None:
            self.executed.append((sql, params))
            if sql.startswith("SHOW COLUMNS"):
                table = sql.split("`")[1]
                self._last_result = (
                    ("shift_id",)
                    if (table, params[0]) in self.columns
                    else None
                )
            elif sql.startswith("SHOW INDEX"):
                table = sql.split("`")[1]
                self._last_result = (
                    ("idx",)
                    if (table, params[0]) in self.indexes
                    else None
                )
            else:
                self._last_result = None

        def fetchone(self):
            return self._last_result

    store = ut.MySQLStore.__new__(ut.MySQLStore)
    cursor = FakeCursor()

    store._ensure_column(
        cursor,
        "app_usage",
        "shift_id",
        "ALTER TABLE app_usage ADD COLUMN shift_id TINYINT",
    )
    store._ensure_column(
        cursor,
        "website_usage",
        "shift_id",
        "ALTER TABLE website_usage ADD COLUMN shift_id TINYINT",
    )
    store._ensure_index(
        cursor,
        "app_usage",
        "idx_app_shift",
        "ALTER TABLE app_usage ADD INDEX idx_app_shift (shift_id)",
    )
    store._ensure_index(
        cursor,
        "website_usage",
        "idx_web_shift",
        "ALTER TABLE website_usage ADD INDEX idx_web_shift (shift_id)",
    )

    ddl = [sql for sql, _ in cursor.executed if sql.startswith("ALTER TABLE")]
    assert ddl == [
        "ALTER TABLE website_usage ADD COLUMN shift_id TINYINT",
        "ALTER TABLE website_usage ADD INDEX idx_web_shift (shift_id)",
    ]
