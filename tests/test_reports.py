from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from report_generator import extract_search_query, load_website_details
from report_utils import ensure_table_logs
from shift_manager import create_shift_manager
from weekly_report import check_shift_data_volume


def test_search_extraction_decoding() -> None:
    url = "https://www.google.com/search?q=hello%20world"
    assert extract_search_query(url) == "hello world"
    url = "https://www.bing.com/search?q=python"
    assert extract_search_query(url) == "python"
    url = "https://duckduckgo.com/?q=test+query"
    assert extract_search_query(url) == "test query"
    url = "https://www.youtube.com/results?search_query=lofi+beats"
    assert extract_search_query(url) == "lofi beats"


def test_load_website_details_dedup(tmp_path: Path) -> None:
    path = tmp_path / "website_visits.csv"
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
    assert len(details["google.com"]) == 1


def test_ensure_table_logs_backfills_from_db(tmp_path: Path) -> None:
    pipeline = create_shift_manager(
        tmp_path / "shift_data",
        log_path=tmp_path / "user_log.txt",
        database_path=tmp_path / "user_log.db",
        export_dir=tmp_path,
    )
    try:
        pipeline.log(
            "APP_USAGE",
            {
                "started_at": "2026-03-17T10:00:00Z",
                "ended_at": "2026-03-17T10:10:00Z",
                "duration_seconds": 600,
                "process_name": "chrome.exe",
                "app_name": "chrome",
                "window_title": "Google Chrome",
            },
        )
        pipeline.log(
            "WEBSITE_VISIT",
            {
                "visited_at": "2026-03-17T10:05:00Z",
                "browser": "chrome",
                "domain": "google.com",
                "url": "https://www.google.com/search?q=test",
                "page_title": "test - Google Search",
                "source": "history_poll",
            },
        )
        pipeline.log(
            "WEBSITE_USAGE",
            {
                "started_at": "2026-03-17T10:00:00Z",
                "ended_at": "2026-03-17T10:10:00Z",
                "duration_seconds": 600,
                "browser": "chrome",
                "domain": "google.com",
                "url": "https://www.google.com/search?q=test",
                "page_title": "test - Google Search",
                "source": "active_window",
            },
        )
        pipeline.log(
            "MEDIA_PLAYBACK",
            {
                "started_at": "2026-03-17T10:15:00Z",
                "ended_at": "2026-03-17T10:20:00Z",
                "duration_seconds": 300,
                "source_app": "Spotify",
                "title": "Song A",
                "artist": "Artist A",
                "playback_state": "playing",
            },
        )
    finally:
        pipeline.close()

    table_log_dir = tmp_path / "table_logs"
    written = ensure_table_logs(table_log_dir, tmp_path / "user_log.db")

    assert written["app_usage.csv"] == 1
    assert written["website_visits.csv"] == 1
    assert written["website_usage.csv"] == 1
    assert written["media_playback.csv"] == 1

    details = load_website_details(
        table_log_dir / "website_visits.csv",
        datetime(2026, 3, 17, tzinfo=timezone.utc).date(),
    )
    assert details["google.com"] == ["https://www.google.com/search?q=test"]


def test_check_shift_data_volume_uses_csv_size(tmp_path: Path) -> None:
    shift_dir = tmp_path / "shift_data"
    daily_dir = shift_dir / "daily_csvs"
    daily_dir.mkdir(parents=True)

    (daily_dir / "small.csv").write_bytes(b"0" * 1024)
    assert check_shift_data_volume(shift_dir) is False

    (daily_dir / "large.csv").write_bytes(b"1" * 10_000_000)
    assert check_shift_data_volume(shift_dir) is True
