from __future__ import annotations

from pathlib import Path

import usage_tracker as ut


def test_csv_write_and_read(tmp_path: Path) -> None:
    table_store = ut.LocalTableStore(tmp_path)
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
    path = tmp_path / "media_playback.csv"
    data = path.read_text(encoding="utf-8")
    assert "Edge" in data


def test_append_only_master_log_uses_user_log_name(tmp_path: Path) -> None:
    pipeline = ut.create_shift_manager(
        base_dir=tmp_path,
        log_path=tmp_path / "user_log.txt",
        database_path=tmp_path / "user_log.db",
        export_dir=tmp_path,
    )
    pipeline.write(
        "APP_USAGE",
        {
            "ended_at": "2026-03-17T10:01:00Z",
            "duration_seconds": 60,
            "app_name": "Code",
            "window_title": "repo",
        },
    )
    pipeline.master_log.flush()
    data = (tmp_path / "user_log.txt").read_text(encoding="utf-8")
    assert "| APP | Code |" in data
