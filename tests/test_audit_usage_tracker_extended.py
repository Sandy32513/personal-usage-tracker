from __future__ import annotations

import csv
import json
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.usage_tracker as sut
import usage_tracker as ut


UTC = timezone.utc


class FakePipelineStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.events: list[tuple[str, dict]] = []
        self.last_success_time: float | None = time_value()
        self.last_failure_time: float | None = None
        self.last_db_success_time: float | None = time_value()
        self.last_db_failure_time: float | None = None
        self.database = SimpleNamespace(disabled_reason=None)
        self.closed = False
        self.processed = False

    def write(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))

    def log(self, event_type: str, payload: dict) -> None:
        self.write(event_type, payload)

    def process_scheduled_tasks(self) -> dict[str, bool]:
        self.processed = True
        return {"processed": True}

    def close(self) -> None:
        self.closed = True


class DummyHistoryPoller:
    def __init__(self) -> None:
        self.recent_visits: dict[str, deque] = {"chrome": deque(maxlen=200)}
        self.events: list[dict] = []
        self.active_result = (None, None, None)
        self.session_result = (None, None, None)

    def poll(self) -> list[dict]:
        return list(self.events)

    def infer_active_url(
        self,
        browser: str,
        window_title: str,
        now: datetime,
    ) -> tuple[str | None, str | None, str | None]:
        return self.active_result

    def infer_session_url(
        self,
        browser: str,
        window_title: str,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[str | None, str | None, str | None]:
        return self.session_result


class DummyMediaPoller:
    def __init__(self, *args, **kwargs) -> None:
        self.poll_interval = kwargs.get("poll_interval", 1.0)
        self.last_run_time: float | None = time_value()
        self.last_success_time: float | None = time_value()
        self.last_error_time: float | None = None
        self.started = False
        self.stopped = False
        self.flushed: list[datetime] = []
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float = 2.0) -> None:
        return None

    def restart(self) -> bool:
        self.started = True
        self.last_run_time = time_value()
        return True

    def is_alive(self) -> bool:
        return True

    def flush_all(self, now: datetime) -> None:
        self.flushed.append(now)


class DummyMySQLStore:
    def __init__(self, *args, **kwargs) -> None:
        self.enabled = True
        self.disabled_reason: str | None = None
        self.disabled_until: float | None = None
        self.last_success_time: float | None = time_value()
        self.last_error_time: float | None = None
        self.buffer: deque[tuple[str, tuple]] = deque()
        self.app_usage: list[dict] = []
        self.website_usage: list[dict] = []
        self.website_visit: list[dict] = []
        self.media_playback: list[dict] = []
        self.media_track_change: list[dict] = []
        self.closed = False
        self.reconnects = 0
        self.clear_result = True

    def _maybe_reconnect(self) -> None:
        self.reconnects += 1

    def flush_buffer_safe(self) -> None:
        return None

    def insert_app_usage(self, payload: dict) -> None:
        self.app_usage.append(payload)

    def insert_website_usage(self, payload: dict) -> None:
        self.website_usage.append(payload)

    def insert_website_visit(self, payload: dict) -> None:
        self.website_visit.append(payload)

    def insert_media_playback(self, payload: dict) -> None:
        self.media_playback.append(payload)

    def insert_media_track_change(self, payload: dict) -> None:
        self.media_track_change.append(payload)

    def clear_all_usage_tables(self) -> bool:
        return self.clear_result

    def close(self) -> None:
        self.closed = True


def time_value() -> float:
    return datetime.now(tz=UTC).timestamp()


def build_tracker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    weekly_reset_enabled: bool = False,
) -> ut.UsageTracker:
    pipeline = FakePipelineStore(tmp_path / "user_log.db")
    history = DummyHistoryPoller()

    monkeypatch.setattr(sut, "create_shift_manager", lambda **kwargs: pipeline)
    monkeypatch.setattr(sut, "BrowserHistoryPoller", lambda: history)
    monkeypatch.setattr(sut, "MediaSessionPoller", DummyMediaPoller)
    monkeypatch.setattr(sut, "MySQLStore", DummyMySQLStore)
    monkeypatch.setattr(sut.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(sut.atexit, "register", lambda *args, **kwargs: None)
    monkeypatch.setattr(sut.win32api, "SetConsoleCtrlHandler", lambda *args, **kwargs: True)

    config = ut.TrackerConfig(
        mysql_host="localhost",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="secret",
        mysql_database="tracker_db",
        log_file=tmp_path / "user_log.txt",
        table_log_dir=tmp_path / "table_logs",
        state_file=tmp_path / "tracker_state.json",
        poll_interval=0.5,
        history_poll_interval=1.0,
        weekly_reset_enabled=weekly_reset_enabled,
        weekly_reset_weekday=6,
        weekly_reset_hour=0,
        weekly_reset_minute=0,
        archive_log_on_weekly_reset=True,
        weekly_archive_dir=tmp_path / "weekly_archives",
        weekly_archive_clear_csv=True,
        quiet=True,
    )
    tracker = ut.UsageTracker(config)
    tracker.history_poller = history
    return tracker


def test_security_helpers_and_bool_parsing(tmp_path: Path) -> None:
    safe_dir = tmp_path / "safe"
    safe_dir.mkdir()
    safe_file = safe_dir / "child.txt"
    safe_file.write_text("ok", encoding="utf-8")
    sibling = tmp_path / "safe-evil" / "child.txt"
    sibling.parent.mkdir()
    sibling.write_text("bad", encoding="utf-8")

    assert ut.extract_domain("https://user:pw@www.example.com:443/path") == "example.com"
    assert ut.extract_domain("notaurl") is None
    assert ut.normalize_title("My File - Visual Studio Code") == "my file visual studio code"
    assert ut.strip_browser_suffix("chrome", "Search - Google Chrome") == "Search"
    assert ut.is_web_url("https://example.com")
    assert not ut.is_web_url("file:///tmp")

    redacted_url = ut.redact_url(
        "https://example.com?a=1&password=secret&token=abc&safe=ok"
    )
    assert "password" not in redacted_url
    assert "token" not in redacted_url
    assert "safe=ok" in redacted_url
    assert "[REDACTED]" in ut.redact_window_title("email me at user@example.com 123-45-6789")

    assert ut.validate_path_safe(safe_file, safe_dir)
    assert not ut.validate_path_safe(sibling, safe_dir)
    assert ut.sanitize_path(sibling, safe_dir) == safe_dir

    masked = ut.mask_credentials_in_log(
        "password: hunter2 token=abc api_key=xyz Bearer 12345"
    )
    assert "hunter2" not in masked
    assert "abc" not in masked
    assert "xyz" not in masked
    assert "12345" not in masked
    assert "[REDACTED]" in masked

    assert ut.parse_bool(True) is True
    assert ut.parse_bool("yes") is True
    assert ut.parse_bool("off", default=True) is False
    assert ut.parse_bool(None, default=True) is True


def test_local_text_store_rotation_and_weekly_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sut, "LOG_ROTATE_BYTES", 10)
    log_path = tmp_path / "user_log.txt"
    log_path.write_text("01234567890", encoding="utf-8")
    store = ut.LocalTextStore(log_path)

    store.write("APP_USAGE", {"value": 1})
    rotated = list(tmp_path.glob("user_log_*.txt"))
    assert rotated
    assert "APP_USAGE" in log_path.read_text(encoding="utf-8")

    weekly_log = tmp_path / "weekly_user_log.txt"
    weekly_log.write_text("content", encoding="utf-8")
    clear_store = ut.LocalTextStore(weekly_log)
    archive_path = clear_store.clear_weekly(archive=True)
    assert archive_path is not None
    assert archive_path.exists()
    assert weekly_log.read_text(encoding="utf-8") == ""


def test_local_table_store_writes_and_archives(tmp_path: Path) -> None:
    table_store = ut.LocalTableStore(tmp_path / "tables")
    timestamp = "2026-03-17T10:00:00Z"
    table_store.write_app_usage(
        {
            "logged_at": timestamp,
            "started_at": timestamp,
            "ended_at": timestamp,
            "duration_seconds": 5,
            "process_name": "code.exe",
            "app_name": "VS Code",
            "window_title": "tracker",
        }
    )
    table_store.write_website_usage(
        {
            "logged_at": timestamp,
            "started_at": timestamp,
            "ended_at": timestamp,
            "duration_seconds": 5,
            "browser": "chrome",
            "domain": "example.com",
            "url": "https://example.com",
            "page_title": "Example",
            "source": "active_window",
        }
    )
    table_store.write_website_visit(
        {
            "logged_at": timestamp,
            "visited_at": timestamp,
            "browser": "chrome",
            "domain": "example.com",
            "url": "https://example.com",
            "page_title": "Example",
            "source": "history",
        }
    )
    table_store.write_media_playback(
        {
            "logged_at": timestamp,
            "started_at": timestamp,
            "ended_at": timestamp,
            "duration_seconds": 5,
            "source_app": "spotify",
            "title": "Song",
            "artist": "Artist",
            "playback_state": "playing",
        }
    )
    table_store.write_media_track_change(
        {
            "logged_at": timestamp,
            "changed_at": timestamp,
            "source_app": "spotify",
            "title": "Song",
            "artist": "Artist",
            "playback_state": "paused",
        }
    )

    archive_dir = tmp_path / "archive"
    table_store.archive_week(archive_dir, "2026-03-17", clear_after=True)
    assert (archive_dir / "2026-03-17" / "app_usage.csv").exists()
    assert not any((tmp_path / "tables").glob("*.csv"))


def test_mysql_store_connect_and_execute_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[tuple[str, tuple | None]] = []

    class FakeCursor:
        def __init__(self) -> None:
            self._result = None

        def execute(self, sql: str, params=None) -> None:
            executed.append((sql, params))
            if sql.startswith("SHOW COLUMNS") or sql.startswith("SHOW INDEX"):
                self._result = None
            else:
                self._result = None

        def fetchone(self):
            return self._result

        def close(self) -> None:
            return None

    class FakeConnection:
        def __init__(self) -> None:
            self.connected = True
            self.reconnect_calls = 0

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def close(self) -> None:
            self.connected = False

        def is_connected(self) -> bool:
            return self.connected

        def reconnect(self, attempts: int = 2, delay: int = 1) -> None:
            self.reconnect_calls += 1
            self.connected = True

    connections: list[FakeConnection] = []

    def fake_connect(**kwargs):
        conn = FakeConnection()
        connections.append(conn)
        return conn

    fake_mysql = SimpleNamespace(connector=SimpleNamespace(connect=fake_connect))
    monkeypatch.setattr(sut, "mysql", fake_mysql)

    store = ut.MySQLStore(
        host="127.0.0.1",
        port=3306,
        user="root",
        password="pw",
        database="tracker_db",
    )
    assert store.enabled is True
    assert any("CREATE DATABASE IF NOT EXISTS" in sql for sql, _ in executed)

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
    store.close()
    assert any("INSERT INTO app_usage" in sql for sql, _ in executed)

    unsafe = ut.MySQLStore(
        host="127.0.0.1",
        port=3306,
        user="root",
        password="pw",
        database="tracker;DROP",
    )
    assert unsafe.enabled is False
    assert unsafe.disabled_reason is not None


def test_null_store_and_pipeline_adapter() -> None:
    null_store = ut.NullTableStore()
    assert null_store.write_app_usage({}) is None
    assert null_store.archive_week(Path("."), "week", False) is None

    pipeline = FakePipelineStore(Path("user_log.db"))
    adapter = ut.PipelineDatabaseAdapter(pipeline)
    payload = {"value": 1}
    adapter.insert_app_usage(payload)
    adapter.insert_website_usage(payload)
    adapter.insert_website_visit(payload)
    adapter.insert_media_playback(payload)
    adapter.insert_media_track_change(payload)
    adapter.flush_buffer_safe()
    assert pipeline.processed is True
    assert adapter.clear_all_usage_tables() is False
    adapter.close()
    assert pipeline.closed is True


def test_browser_history_poller_poll_and_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sut.BrowserHistoryPoller, "_discover_sources", lambda self: [])
    poller = ut.BrowserHistoryPoller()

    source = ut.HistorySource("chrome", "chromium", tmp_path / "History", "chrome:test")
    source.path.write_text("db", encoding="utf-8")

    def fake_query(path: Path, query: str, params: tuple) -> list[tuple]:
        if "moz_historyvisits" in query:
            return [
                (
                    "https://firefox.example",
                    "Firefox Title",
                    int(datetime(2026, 3, 17, 10, 2, tzinfo=UTC).timestamp() * 1_000_000),
                ),
            ]
        return [
            ("https://example.com/one", "Example One", poller.last_marker.get(source.key, 0) + 1),
            ("not-a-web-url", "Ignored", poller._to_chromium_us(datetime(2026, 3, 17, 10, 1, tzinfo=UTC))),
        ]

    monkeypatch.setattr(poller, "_query_sqlite_copy", fake_query)
    poller.last_marker[source.key] = 0
    chromium_events = poller._poll_chromium(source)
    assert len(chromium_events) == 1
    assert chromium_events[0]["domain"] == "example.com"

    firefox_source = ut.HistorySource("firefox", "firefox", tmp_path / "places.sqlite", "firefox:test")
    firefox_source.path.write_text("db", encoding="utf-8")
    poller.last_marker[firefox_source.key] = 0
    firefox_events = poller._poll_firefox(firefox_source)
    assert firefox_events[0]["domain"] == "firefox.example"

    poller.sources = [source, firefox_source]
    poller.last_marker[source.key] = 0
    poller.last_marker[firefox_source.key] = 0
    events = poller.poll()
    assert [event["browser"] for event in events] == ["chrome", "firefox"]

    now = datetime(2026, 3, 17, 10, 5, tzinfo=UTC)
    poller.recent_visits["chrome"].append(
        {
            "visited_at": now - timedelta(seconds=10),
            "url": "https://example.com/search",
            "domain": "example.com",
            "page_title": "Search Results",
        }
    )
    assert poller.infer_active_url("chrome", "Search Results - Google Chrome", now)[0] == "https://example.com/search"
    assert poller.infer_session_url(
        "chrome",
        "Search Results - Google Chrome",
        now - timedelta(seconds=30),
        now,
    )[1] == "example.com"


def test_media_session_poller_helper_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_store = FakePipelineStore(tmp_path / "user_log.db")
    table_store = ut.LocalTableStore(tmp_path / "tables")
    mysql_store = DummyMySQLStore()
    stop_event = threading.Event()
    poller = ut.MediaSessionPoller(
        local_store=local_store,
        table_store=table_store,
        mysql_store=mysql_store,
        stop_event=stop_event,
        poll_interval=1.5,
    )

    assert poller._normalize_playback_status(SimpleNamespace(name="PlaybackStatus.PLAYING")) == "playing"
    assert poller._position_seconds(timedelta(seconds=5)) == 5
    assert poller._position_seconds(SimpleNamespace(duration=20_000_000)) == 2
    assert poller._position_seconds(None) is None
    assert poller._safe_timeline_position(SimpleNamespace(get_timeline_properties=lambda: SimpleNamespace(position=timedelta(seconds=7)))) == 7
    assert poller._safe_timeline_position(SimpleNamespace(get_timeline_properties=lambda: (_ for _ in ()).throw(RuntimeError("boom")))) is None

    state = ut.MediaPlaybackState(
        source_app="spotify",
        title="Song",
        artist="Artist",
        playback_state="playing",
        started_at=datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
        last_seen=datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
        is_playing=True,
        track_id="Song|Artist",
        accumulated_seconds=0,
        last_position_seconds=1.0,
        last_poll_time=datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
    )
    poller._update_accumulated(
        state,
        datetime(2026, 3, 17, 10, 0, 5, tzinfo=UTC),
        6.0,
        1.5,
    )
    assert state.accumulated_seconds == 5.0

    poller.session_states["spotify"] = state
    poller.flush_all(datetime(2026, 3, 17, 10, 0, 10, tzinfo=UTC))
    assert mysql_store.media_playback

    class FakeThread:
        def __init__(self, alive: bool) -> None:
            self._alive = alive

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout: float = 2.0) -> None:
            self._alive = False

    poller.thread = FakeThread(True)  # type: ignore[assignment]
    assert poller.restart() is True
    poller.stop()
    poller.join()


def test_usage_tracker_state_weekly_reset_and_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = build_tracker(tmp_path, monkeypatch, weekly_reset_enabled=True)
    tracker.state = {}
    tracker._weekly_last_check = datetime(2026, 3, 16, tzinfo=UTC)
    tracker.history_poller.events = [
        {
            "visited_at": datetime(2026, 3, 17, 10, 0, tzinfo=UTC),
            "browser": "chrome",
            "domain": "example.com",
            "url": "https://example.com",
            "page_title": "Example",
            "source": "browser_history",
        }
    ]
    tracker._poll_history(datetime(2026, 3, 17, 10, 1, tzinfo=UTC), force=True)
    assert tracker.mysql_store.website_visit

    tracker.state = {"keep": "value"}
    assert tracker._save_state() is True
    loaded = tracker._load_state()
    assert loaded["keep"] == "value"
    tracker.config.state_file.write_text("{bad", encoding="utf-8")
    assert tracker._load_state() == {}

    reset_time = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    tracker._weekly_last_check = reset_time - timedelta(minutes=1)
    tracker.media_poller = DummyMediaPoller()
    tracker.history_poller.recent_visits["chrome"].append({"visited_at": reset_time, "url": "https://example.com", "domain": "example.com", "page_title": "Example"})
    tracker._maybe_weekly_reset(reset_time)
    assert tracker.state["last_weekly_reset_key"] == "2026-03-22T00:00"
    event_types = [event_type for event_type, _ in tracker.local_store.events]
    assert "WEEKLY_ARCHIVE" in event_types
    assert "WEEKLY_RESET" in event_types


def test_usage_tracker_session_flow_and_run_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = build_tracker(tmp_path, monkeypatch, weekly_reset_enabled=False)
    tracker.history_poller.active_result = ("https://example.com", "example.com", "Example Page")
    tracker.history_poller.session_result = ("https://example.com/final", "example.com", "Final Page")

    now = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    window = {
        "process_name": "chrome.exe",
        "app_name": "chrome",
        "window_title": "Example Page - Google Chrome",
    }
    tracker._start_session(window, now)
    assert tracker.current_session is not None
    tracker._refresh_session_browser_fields(now + timedelta(seconds=1))
    tracker._flush_session(now + timedelta(seconds=5))
    assert tracker.current_session is None
    assert tracker.mysql_store.app_usage
    assert tracker.mysql_store.website_usage

    tracker._handle_window(window, now)
    tracker._handle_window(None, now + timedelta(seconds=5))
    assert any(event_type == "APP_USAGE" for event_type, _ in tracker.local_store.events)

    wait_calls: list[float] = []
    tracker.stop_event.wait = lambda value: wait_calls.append(value)  # type: ignore[assignment]
    tracker._get_foreground_window = lambda: None  # type: ignore[assignment]
    tracker.run_cycle()
    assert wait_calls[-1] == tracker.config.poll_interval

    tracker._finalize()
    assert tracker.mysql_store.closed is True


def test_foreground_window_helpers_and_process_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = build_tracker(tmp_path, monkeypatch)
    monkeypatch.setattr(sut.win32gui, "GetForegroundWindow", lambda: 10)
    monkeypatch.setattr(sut.win32gui, "GetWindowText", lambda hwnd: "Window")
    monkeypatch.setattr(sut.win32process, "GetWindowThreadProcessId", lambda hwnd: (1, 123))
    monkeypatch.setattr(sut.psutil, "Process", lambda pid: SimpleNamespace(name=lambda: "python.exe"))
    window = tracker._get_foreground_window()
    assert window == {
        "pid": 123,
        "process_name": "python.exe",
        "app_name": "python",
        "window_title": "Window",
    }

    guard_path = tmp_path / ".tracker.lock"
    guard = ut.SingleInstanceGuard(guard_path)
    assert guard.acquire() is True
    assert guard_path.exists()
    guard.release()
    assert not guard_path.exists()

    guard_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(sut.psutil, "pid_exists", lambda pid: False)
    guard = ut.SingleInstanceGuard(guard_path)
    assert guard.acquire() is True


def test_parse_args_build_config_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sut.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            mysql_host="127.0.0.1",
            mysql_port=3306,
            mysql_user="root",
            mysql_password="pw",
            mysql_database="tracker",
            use_sqlserver="false",
            sqlserver_host="",
            sqlserver_port=1433,
            sqlserver_user="",
            sqlserver_password="",
            sqlserver_database="tracker",
            log_file=str(tmp_path / "user_log.txt"),
            database_file=str(tmp_path / "user_log.db"),
            table_log_dir=str(tmp_path / "table_logs"),
            daily_output_dir=str(tmp_path),
            poll_interval=0.1,
            history_poll_interval=0.1,
            state_file=str(tmp_path / "state.json"),
            weekly_reset_enabled="true",
            weekly_reset_weekday=8,
            weekly_reset_hour=30,
            weekly_reset_minute=-1,
            archive_log_on_weekly_reset="false",
            quiet=True,
        ),
    )
    args = ut.parse_args()
    config = ut.build_config(args)
    assert config.weekly_reset_enabled is True
    assert config.weekly_reset_weekday == 6
    assert config.weekly_reset_hour == 23
    assert config.weekly_reset_minute == 0

    class DummyTracker:
        def __init__(self, config: ut.TrackerConfig) -> None:
            self.config = config
            self.ran = False

        def run(self) -> None:
            self.ran = True

    releases: list[str] = []

    class DummyGuard:
        def __init__(self, path: Path) -> None:
            self.path = path

        def acquire(self) -> bool:
            return True

        def release(self) -> None:
            releases.append("released")

        def _read_pid(self) -> int:
            return 1

    monkeypatch.setattr(sut, "UsageTracker", DummyTracker)
    monkeypatch.setattr(sut, "SingleInstanceGuard", DummyGuard)
    ut.main()
    assert releases == ["released"]
