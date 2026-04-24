from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import usage_tracker as ut


UTC = timezone.utc


class DummyLocalStore:
    def __init__(self) -> None:
        self.events = []

    def write(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class DummyTableStore:
    def __init__(self) -> None:
        self.media_playback = []
        self.media_track_changes = []

    def write_media_playback(self, payload: dict) -> None:
        self.media_playback.append(payload)

    def write_media_track_change(self, payload: dict) -> None:
        self.media_track_changes.append(payload)


class DummyMySQL:
    def __init__(self) -> None:
        self.media_playback = []
        self.media_track_changes = []

    def insert_media_playback(self, payload: dict) -> None:
        self.media_playback.append(payload)

    def insert_media_track_change(self, payload: dict) -> None:
        self.media_track_changes.append(payload)


class DummyStopEvent:
    def is_set(self) -> bool:
        return False

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


@pytest.fixture
def media_poller() -> ut.MediaSessionPoller:
    local = DummyLocalStore()
    table = DummyTableStore()
    mysql = DummyMySQL()
    poller = ut.MediaSessionPoller(local, table, mysql, DummyStopEvent(), 1.0)
    return poller


def test_single_session_duration(media_poller: ut.MediaSessionPoller) -> None:
    now = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    session = DummySession("Edge", "Song A", "Artist A", "playing", 0)
    media_poller.manager = DummyManager([session])
    media_poller._poll_once(now)

    session._pos = 30
    media_poller._poll_once(now + timedelta(seconds=30))

    session._status = "paused"
    media_poller._poll_once(now + timedelta(seconds=40))

    assert len(media_poller.mysql_store.media_playback) == 1
    duration = media_poller.mysql_store.media_playback[0]["duration_seconds"]
    assert duration >= 30


def test_multi_session_dedup(media_poller: ut.MediaSessionPoller) -> None:
    now = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    session_a = DummySession("Edge", "Song A", "Artist A", "playing", 0)
    session_b = DummySession("Spotify", "Song B", "Artist B", "playing", 0)
    media_poller.manager = DummyManager([session_a, session_b])
    media_poller._poll_once(now)
    media_poller._poll_once(now + timedelta(seconds=1))

    track_events = media_poller.mysql_store.media_track_changes
    assert len(track_events) == 2


def test_track_change_flushes(media_poller: ut.MediaSessionPoller) -> None:
    now = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    session = DummySession("Edge", "Song A", "Artist A", "playing", 5)
    media_poller.manager = DummyManager([session])
    media_poller._poll_once(now)

    session._pos = 40
    session._title = "Song B"
    media_poller._poll_once(now + timedelta(seconds=30))

    assert len(media_poller.mysql_store.media_playback) >= 1
