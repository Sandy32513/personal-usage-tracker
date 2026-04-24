from __future__ import annotations

import csv
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from report_generator import extract_search_query, load_website_details
from usage_tracker import (
    LocalTableStore,
    MediaPlaybackState,
    MediaSessionPoller,
    mysql_dt,
)


UTC = timezone.utc


class DummyLocalStore:
    def __init__(self) -> None:
        self.events = []

    def write(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class DummyMySQLStore:
    def __init__(self) -> None:
        self.media_playback = []
        self.media_track_changes = []

    def insert_media_playback(self, payload: dict) -> None:
        self.media_playback.append(payload)

    def insert_media_track_change(self, payload: dict) -> None:
        self.media_track_changes.append(payload)


class DummyStopEvent:
    def __init__(self) -> None:
        self._flag = False

    def is_set(self) -> bool:
        return self._flag

    def wait(self, _timeout: float) -> None:
        return None


class DummyTimeline:
    def __init__(self, seconds: float) -> None:
        self.position = timedelta(seconds=seconds)


class DummyPlaybackInfo:
    def __init__(self, status: str) -> None:
        self.playback_status = SimpleNamespace(name=status)


class DummyMediaProps:
    def __init__(self, title: str, artist: str) -> None:
        self.title = title
        self.artist = artist


class DummySession:
    def __init__(self, app_id: str, title: str, artist: str, status: str, pos: float) -> None:
        self.source_app_user_model_id = app_id
        self._title = title
        self._artist = artist
        self._status = status
        self._pos = pos

    def get_playback_info(self) -> DummyPlaybackInfo:
        return DummyPlaybackInfo(self._status)

    def try_get_media_properties_async(self) -> SimpleNamespace:
        return SimpleNamespace(get=lambda: DummyMediaProps(self._title, self._artist))

    def get_timeline_properties(self) -> DummyTimeline:
        return DummyTimeline(self._pos)


class DummyManager:
    def __init__(self, sessions: list[DummySession]) -> None:
        self._sessions = sessions

    def get_sessions(self) -> list[DummySession]:
        return list(self._sessions)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_search_extraction() -> None:
    url = "https://www.google.com/search?q=hello%20world"
    assert_true(extract_search_query(url) == "hello world", "Google search decode failed")
    url = "https://www.bing.com/search?q=python"
    assert_true(extract_search_query(url) == "python", "Bing search decode failed")
    url = "https://duckduckgo.com/?q=test+query"
    assert_true(extract_search_query(url) == "test query", "DuckDuckGo search decode failed")
    url = "https://www.youtube.com/results?search_query=lofi+beats"
    assert_true(extract_search_query(url) == "lofi beats", "YouTube search decode failed")
    print("test_search_extraction passed")


def test_load_website_details_dedup() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "website_visits.csv"
        rows = [
            {
                "visited_at": "2026-03-17T10:00:00Z",
                "domain": "google.com",
                "url": "https://www.google.com/search?q=test",
            },
            {
                "visited_at": "2026-03-17T10:05:00Z",
                "domain": "google.com",
                "url": "https://www.google.com/search?q=test",
            },
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        details = load_website_details(path, datetime(2026, 3, 17).date())
        assert_true(len(details["google.com"]) == 1, "Deduplication failed")
        print("test_load_website_details_dedup passed")


def test_media_tracking_durations() -> None:
    now = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    local_store = DummyLocalStore()
    mysql_store = DummyMySQLStore()
    table_store = LocalTableStore(Path(tempfile.mkdtemp()))
    poller = MediaSessionPoller(local_store, table_store, mysql_store, DummyStopEvent(), 1.0)

    session = DummySession("Edge", "Song A", "Artist A", "playing", 0)
    poller.manager = DummyManager([session])
    poller._poll_once(now)

    session._pos = 30
    poller._poll_once(now + timedelta(seconds=30))

    session._status = "paused"
    poller._poll_once(now + timedelta(seconds=40))

    assert_true(len(mysql_store.media_playback) == 1, "Playback not flushed on pause")
    duration = mysql_store.media_playback[0]["duration_seconds"]
    assert_true(duration >= 30, "Playback duration incorrect")
    print("test_media_tracking_durations passed")


def test_multi_session_tracking() -> None:
    now = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    local_store = DummyLocalStore()
    mysql_store = DummyMySQLStore()
    table_store = LocalTableStore(Path(tempfile.mkdtemp()))
    poller = MediaSessionPoller(local_store, table_store, mysql_store, DummyStopEvent(), 1.0)

    session_a = DummySession("Edge", "Song A", "Artist A", "playing", 5)
    session_b = DummySession("Spotify", "Song B", "Artist B", "playing", 5)
    poller.manager = DummyManager([session_a, session_b])
    poller._poll_once(now)

    session_a._pos = 40
    session_b._pos = 50
    poller._poll_once(now + timedelta(seconds=35))

    session_a._status = "paused"
    session_b._status = "paused"
    poller._poll_once(now + timedelta(seconds=40))

    assert_true(len(mysql_store.media_playback) == 2, "Multi-session flush missing")
    apps = {entry["source_app"] for entry in mysql_store.media_playback}
    assert_true("Edge" in apps and "Spotify" in apps, "Session mapping incorrect")
    print("test_multi_session_tracking passed")


def test_csv_integrity() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        table_store = LocalTableStore(Path(tmpdir))
        payload = {
            "logged_at": "2026-03-17T10:00:00Z",
            "started_at": "2026-03-17T10:00:00Z",
            "ended_at": "2026-03-17T10:01:00Z",
            "duration_seconds": 60,
            "source_app": "Edge",
            "title": "Song",
            "artist": "Artist",
            "playback_state": "playing",
        }
        table_store.write_media_playback(payload)
        path = Path(tmpdir) / "media_playback.csv"
        with path.open("r", encoding="utf-8") as handle:
            data = handle.read()
        assert_true("Edge" in data, "CSV write failed")
        print("test_csv_integrity passed")


def main() -> None:
    print("Running usage tracker tests...")
    test_search_extraction()
    test_load_website_details_dedup()
    test_media_tracking_durations()
    test_multi_session_tracking()
    test_csv_integrity()
    print("All tests passed.")


if __name__ == "__main__":
    main()
