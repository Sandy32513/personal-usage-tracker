from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import openpyxl

import src.shift_manager as ssm


UTC = timezone.utc


def test_shift_manager_helper_functions() -> None:
    now_utc = ssm.utc_now()
    now_local = ssm.local_now()
    assert now_utc.tzinfo is not None
    assert now_local.tzinfo is not None
    assert "." in ssm.format_log_timestamp(datetime(2026, 3, 17, 10, 0, tzinfo=UTC))
    assert ssm.iso_utc(datetime(2026, 3, 17, 10, 0, tzinfo=UTC)).endswith("Z")
    assert ssm.parse_datetime("2026-03-17 10:00:00") is not None
    assert ssm.parse_datetime("2026-03-17T10:00:00Z") is not None
    assert ssm.parse_datetime("") is None
    assert ssm.seconds_to_readable(3661) == "1h 1m 1s"
    assert ssm.safe_json({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'
    assert ssm.category_for_event("APP_USAGE") == "APP"
    assert ssm.category_for_event("MEDIA_TRACK_CHANGE") == "MEDIA"

    entry = ssm.normalize_event(
        "WEBSITE_USAGE",
        {
            "ended_at": "2026-03-17T10:00:00Z",
            "duration_seconds": 60,
            "browser": "chrome",
            "domain": "example.com",
            "url": "https://example.com?q=test",
            "page_title": "Example",
        },
    )
    assert entry.shift_id == 2
    structured_line = entry.to_line()
    parsed = ssm.parse_structured_line(structured_line)
    assert parsed is not None
    assert parsed.event_type == "WEBSITE_USAGE"

    legacy_line = json.dumps(
        {
            "logged_at": "2026-03-17T10:00:00Z",
            "event_type": "APP_USAGE",
            "data": {
                "ended_at": "2026-03-17T10:00:00Z",
                "duration_seconds": 60,
                "app_name": "Code",
                "window_title": "repo",
            },
        }
    )
    legacy = ssm.parse_legacy_json_line(legacy_line)
    assert legacy is not None
    assert ssm.parse_log_line(legacy_line) is not None
    assert ssm._extract_search_query("https://www.google.com/search?q=python%20docs") == "python docs"
    assert ssm._safe_sheet_title("very/long*sheet:name?") == "very/long*sheet:name?"
    assert ssm._parse_shift_key("2026-03-17-shift2") == (date(2026, 3, 17), 2)
    assert ssm._shift_from_order(ssm._shift_order(date(2026, 3, 17), 3)) == (date(2026, 3, 17), 3)


def test_master_log_writer_and_csv_helpers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("USAGE_TRACKER_ENABLE_LOG_BUFFERING", "true")
    writer = ssm.MasterLogWriter(tmp_path / "user_log.txt")
    entry = ssm.normalize_event(
        "APP_USAGE",
        {
            "ended_at": "2026-03-17T10:00:00Z",
            "duration_seconds": 30,
            "app_name": "Code",
            "window_title": "repo",
        },
    )
    writer.append_entry(entry)
    writer.flush()
    assert writer.get_size() > 0
    assert writer.is_healthy() is True
    assert len(list(writer.read_streaming())) == 1
    try:
        writer.clear_weekly(False)
    except RuntimeError as exc:
        assert "append-only" in str(exc)

    replaced = writer.replace_with_entries([entry, entry])
    assert replaced == writer.log_path
    assert len(writer.read_all()) == 2

    csv_path = tmp_path / "entries.csv"
    ssm._write_csv_rows(csv_path, writer.read_all())
    assert csv_path.exists()

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    ssm._write_sheet(sheet, writer.read_all())
    assert sheet.max_row >= 2


def test_event_database_and_shift_manager_paths(tmp_path: Path) -> None:
    db = ssm.EventDatabase(tmp_path / "events.db")
    entry = ssm.normalize_event(
        "APP_USAGE",
        {
            "ended_at": "2026-03-17T10:00:00Z",
            "duration_seconds": 60,
            "app_name": "Code",
            "window_title": "repo",
        },
    )
    second = ssm.normalize_event(
        "MEDIA_PLAYBACK",
        {
            "ended_at": "2026-03-18T10:00:00Z",
            "duration_seconds": 120,
            "source_app": "Spotify",
            "title": "Song",
            "artist": "Artist",
        },
    )
    pending = ssm.normalize_event(
        "WEBSITE_VISIT",
        {
            "visited_at": "2026-03-17T11:00:00Z",
            "browser": "chrome",
            "domain": "example.com",
            "url": "https://example.com",
            "page_title": "Example",
            "source": "history",
        },
    )
    db.upsert_entry(entry, log_written=False)
    db.upsert_entries_batch([entry, second], log_written=True)
    db.upsert_entry(pending, log_written=False)
    assert db.count_events() == 3
    assert len(db.pending_log_entries()) >= 1
    db.mark_log_written(entry.event_key)
    assert db.get_state("missing", "default") == "default"
    db.set_state("cursor", "1")
    assert db.get_state("cursor") == "1"
    db.record_shift_run(date(2026, 3, 17), 2, [entry])
    db.record_daily_export(date(2026, 3, 17), tmp_path / "daily.xlsx")
    assert db.entries_for_date(date(2026, 3, 17))
    assert db.all_entries()
    assert db.min_event_date() == date(2026, 3, 17)
    pruned = db.prune_before(
        datetime(2026, 3, 18, tzinfo=ssm.LOCAL_TZ),
        last_log_offset=0,
    )
    assert pruned["remaining_events"] == 1
    db.close()

    manager = ssm.create_shift_manager(
        base_dir=tmp_path,
        log_path=tmp_path / "user_log.txt",
        database_path=tmp_path / "user_log.db",
        export_dir=tmp_path,
    )
    manager.log_batch(
        [
            (
                "APP_USAGE",
                {
                    "ended_at": "2026-03-17T10:00:00Z",
                    "duration_seconds": 60,
                    "app_name": "Code",
                    "window_title": "repo",
                },
            ),
            (
                "WEBSITE_USAGE",
                {
                    "ended_at": "2026-03-17T10:05:00Z",
                    "duration_seconds": 120,
                    "browser": "chrome",
                    "domain": "example.com",
                    "url": "https://example.com",
                    "page_title": "Example",
                    "source": "active_window",
                },
            ),
        ]
    )
    assert manager.sync_master_log_to_db() >= 0
    assert manager.repair_master_log_from_db() >= 0
    assert manager.entries_for_shift(date(2026, 3, 17), 2)
    shift_csv = manager.generate_shift_csv(date(2026, 3, 17), 2)
    daily_csv = manager.generate_daily_csv(date(2026, 3, 17))
    workbook_path = manager.generate_daily_workbook(date(2026, 3, 17))
    assert shift_csv.exists()
    assert daily_csv.exists()
    assert workbook_path.exists()

    summary = manager.process_daily(date(2026, 3, 17))
    assert summary["daily_csv"].endswith(".csv")
    assert manager.process_weekly(date(2026, 3, 17))["update_date"]
    assert manager.process_scheduled_tasks(datetime(2026, 3, 18, tzinfo=ssm.LOCAL_TZ))
    assert manager.health_check()["master_log_exists"] is True

    legacy_log = tmp_path / "shift_data" / "master_logs" / "master_usage.log"
    legacy_log.parent.mkdir(parents=True, exist_ok=True)
    legacy_log.write_text(entry.to_line() + "\n", encoding="utf-8")
    legacy_csv = tmp_path / "app_usage.csv"
    with legacy_csv.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            "logged_at,started_at,ended_at,duration_seconds,process_name,app_name,window_title\n"
            "2026-03-17T10:00:00Z,2026-03-17T09:00:00Z,2026-03-17T10:00:00Z,60,code.exe,Code,repo\n"
        )
    audit = manager.analyze_existing_sources()
    assert audit.text_log_files >= 1
    assert ssm._legacy_text_sources(tmp_path)
    assert ssm._legacy_csv_sources(tmp_path)
    assert list(ssm._entries_from_legacy_csv(legacy_csv))
    consolidated = manager.consolidate_legacy_logs(delete_old_files=False)
    assert "merged_records" in consolidated

    cutoff_result = manager.prune_before(datetime(2026, 3, 17, tzinfo=ssm.LOCAL_TZ))
    assert "removed_events" in cutoff_result
    manager.close()


def test_retry_and_lockfile(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise OSError("retry")
        return "ok"

    assert ssm.retry(flaky) == "ok"

    locked_path = tmp_path / "locked.txt"
    with ssm.LockFile(locked_path):
        assert locked_path.with_suffix(".txt.lock").exists()
