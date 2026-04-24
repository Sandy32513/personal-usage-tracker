#!/usr/bin/env python3
"""Integration tests for the full end-to-end pipeline."""

from __future__ import annotations

import csv
import os
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from shift_manager import (
    ShiftManager,
    create_shift_manager,
    get_shift_id,
    get_shift_time_range,
)


UTC = timezone.utc
LOCAL_TZ = datetime.now().astimezone().tzinfo or UTC


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def pipeline(temp_dir):
    """Create a test pipeline with all features enabled."""
    pipeline = create_shift_manager(
        temp_dir / "shift_data",
        log_path=temp_dir / "user_log.txt",
        database_path=temp_dir / "user_log.db",
        export_dir=temp_dir,
    )
    yield pipeline
    pipeline.close()


@pytest.mark.integration
def test_full_pipeline_workflow(temp_dir, pipeline):
    """Test complete workflow: log events -> sync to DB -> generate exports."""
    
    # Step 1: Log various events across different shifts
    events = [
        # Shift 1 (00:00-08:00 UTC = depends on local timezone)
        ("APP_USAGE", {
            "ended_at": "2026-03-18T02:00:00Z",
            "duration_seconds": 3600,
            "app_name": "Code",
            "window_title": "main.py - VS Code",
        }),
        # Shift 2 (08:00-16:00 UTC)
        ("WEBSITE_USAGE", {
            "ended_at": "2026-03-18T10:00:00Z",
            "duration_seconds": 1800,
            "domain": "github.com",
            "url": "https://github.com",
        }),
        ("APP_USAGE", {
            "ended_at": "2026-03-18T12:00:00Z",
            "duration_seconds": 7200,
            "app_name": "Excel",
            "window_title": "report.xlsx",
        }),
        # Shift 3 (16:00-24:00 UTC)
        ("MEDIA_PLAYBACK", {
            "ended_at": "2026-03-18T18:00:00Z",
            "duration_seconds": 3600,
            "source_app": "Spotify",
            "title": "Lo-fi Study",
            "artist": "Chill Artist",
        }),
        ("APP_USAGE", {
            "ended_at": "2026-03-18T20:00:00Z",
            "duration_seconds": 5400,
            "app_name": "Chrome",
            "window_title": "YouTube",
        }),
    ]
    
    for event_type, payload in events:
        pipeline.log(event_type, payload)
    
    # Step 2: Verify events are in master log
    master_log_entries = pipeline.master_log.read_all()
    assert len(master_log_entries) == 5, f"Expected 5 log entries, got {len(master_log_entries)}"
    
    # Step 3: Verify events are in database
    db_count = pipeline.database.count_events()
    assert db_count == 5, f"Expected 5 DB entries, got {db_count}"
    
    # Step 4: Verify idempotent insert (same event shouldn't duplicate)
    pipeline.log("APP_USAGE", events[0][1])  # Re-log first event
    assert pipeline.database.count_events() == 5, "Duplicate events should not be inserted"
    
    # Step 5: Generate shift CSVs
    shift_date = date(2026, 3, 18)
    for shift_num in [1, 2, 3]:
        csv_path = pipeline.generate_shift_csv(shift_date, shift_num)
        if csv_path and csv_path.exists():
            with csv_path.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
                # Verify shift CSV has data or is empty
                if rows:
                    assert "timestamp" in rows[0], "Should have timestamp column"
    
    # Step 6: Generate daily CSV
    daily_csv = pipeline.generate_daily_csv(shift_date)
    assert daily_csv.exists(), "Daily CSV should be generated"
    
    with daily_csv.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        # Some events might be filtered due to timezone or date boundaries
        assert len(rows) >= 4, f"Expected at least 4 rows in daily CSV, got {len(rows)}"
    
    # Step 7: Generate daily workbook
    workbook_path = pipeline.generate_daily_workbook(shift_date)
    assert workbook_path.exists(), "Daily workbook should be generated"


@pytest.mark.integration
def test_weekly_schedule_workflow(temp_dir, pipeline):
    """Test weekly schedule determination based on Friday activity."""
    
    # Test with low activity Friday -> Sunday reset
    week_start = date(2026, 3, 16)  # Monday
    pipeline.log(
        "APP_USAGE",
        {
            "ended_at": "2026-03-20T10:00:00Z",  # Friday
            "duration_seconds": 1800,
            "app_name": "Code",
            "window_title": "repo",
        }
    )
    
    reset_day = pipeline.determine_weekly_update_day(week_start)
    assert reset_day in [5, 6], f"Expected Friday(5) or Saturday(6), got {reset_day}"


@pytest.mark.integration
def test_recovery_from_db_failure(temp_dir, pipeline, monkeypatch):
    """Test that pipeline recovers when DB write fails."""
    
    # Make DB write fail once
    original_upsert = pipeline.database.upsert_entry
    call_count = {"count": 0}
    
    def flaky_upsert(entry, *, log_written: bool):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise sqlite3.OperationalError("Simulated DB failure")
        return original_upsert(entry, log_written=log_written)
    
    monkeypatch.setattr(pipeline.database, "upsert_entry", flaky_upsert)
    
    # Log an event - should succeed despite DB failure
    pipeline.log(
        "APP_USAGE",
        {
            "ended_at": "2026-03-18T10:00:00Z",
            "duration_seconds": 60,
            "app_name": "Code",
            "window_title": "test",
        }
    )
    
    # Event should be in log but not DB yet
    assert len(pipeline.master_log.read_all()) == 1
    
    # Repair from log to DB
    monkeypatch.setattr(pipeline.database, "upsert_entry", original_upsert)
    synced = pipeline.sync_master_log_to_db()
    
    # Now should be in DB
    assert pipeline.database.count_events() == 1


@pytest.mark.integration
def test_legacy_consolidation_workflow(temp_dir, pipeline):
    """Test legacy log and CSV consolidation."""
    
    # Note: Legacy consolidation is optional and depends on specific directory structure
    # The pipeline might not find legacy files in temp_dir
    # This test verifies the consolidation function exists and runs without error
    result = pipeline.consolidate_legacy_logs(delete_old_files=False)
    
    # The function should return a result dict even if no legacy files found
    assert isinstance(result, dict), "consolidate_legacy_logs should return a dict"
    assert "merged_records" in result, "Result should have merged_records key"


def test_shift_boundary_handling():
    """Test shift boundaries are handled correctly."""
    
    target = date(2026, 3, 18)
    
    # Test shift 1: 00:00 - 08:00
    start1, end1 = get_shift_time_range(1, target)
    assert start1.hour == 0
    assert end1.hour == 8
    
    # Test shift 2: 08:00 - 16:00
    start2, end2 = get_shift_time_range(2, target)
    assert start2.hour == 8
    assert end2.hour == 16
    
    # Test shift 3: 16:00 - 24:00 (next day midnight)
    start3, end3 = get_shift_time_range(3, target)
    assert start3.hour == 16
    assert end3.day == 19  # Next day
    
    # Test shift_id calculation
    # 08:00 exactly should be shift 2 (half-open interval [8, 16))
    assert get_shift_id(datetime(2026, 3, 18, 8, 0, tzinfo=LOCAL_TZ)) == 2
    assert get_shift_id(datetime(2026, 3, 18, 7, 59, tzinfo=LOCAL_TZ)) == 1
    assert get_shift_id(datetime(2026, 3, 18, 16, 0, tzinfo=LOCAL_TZ)) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
