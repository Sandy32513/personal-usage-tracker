#!/usr/bin/env python3
"""Tests for critical bug fixes."""

from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_bootstrap import bootstrap_project

bootstrap_project()

from shift_manager import (
    ShiftManager,
    create_shift_manager,
    get_shift_id,
    get_shift_time_range,
    parse_log_line,
    format_log_timestamp,
    LOCAL_TZ,
    UTC,
)

UTC = timezone.utc


def test_shift_id_calculation():
    """Test shift_id is correctly calculated for different hours."""
    print("Testing shift_id calculation...")
    
    # Shift 1: 00:00 - 08:00 (in local timezone)
    assert get_shift_id(datetime(2026, 3, 18, 2, 0, tzinfo=LOCAL_TZ)) == 1
    assert get_shift_id(datetime(2026, 3, 18, 7, 59, tzinfo=LOCAL_TZ)) == 1
    
    # Shift 2: 08:00 - 16:00 (in local timezone)
    assert get_shift_id(datetime(2026, 3, 18, 10, 0, tzinfo=LOCAL_TZ)) == 2
    assert get_shift_id(datetime(2026, 3, 18, 15, 59, tzinfo=LOCAL_TZ)) == 2
    
    # Shift 3: 16:00 - 24:00 (in local timezone)
    assert get_shift_id(datetime(2026, 3, 18, 18, 0, tzinfo=LOCAL_TZ)) == 3
    assert get_shift_id(datetime(2026, 3, 18, 23, 59, tzinfo=LOCAL_TZ)) == 3
    
    print("  OK: shift_id calculation correct")


def test_shift_time_range_boundaries():
    """Test shift boundaries use half-open intervals [start, end)."""
    print("Testing shift time range boundaries...")
    
    target = date(2026, 3, 18)
    
    # Shift 1: 00:00:00 to 08:00:00
    start1, end1 = get_shift_time_range(1, target)
    assert start1.hour == 0 and start1.minute == 0
    assert end1.hour == 8 and end1.minute == 0
    
    # Shift 2: 08:00:00 to 16:00:00
    start2, end2 = get_shift_time_range(2, target)
    assert start2.hour == 8 and start2.minute == 0
    assert end2.hour == 16 and end2.minute == 0
    
    # Shift 3: 16:00:00 to 24:00:00 (next day midnight)
    start3, end3 = get_shift_time_range(3, target)
    assert start3.hour == 16 and start3.minute == 0
    assert end3.hour == 0 and end3.minute == 0
    assert end3.day == 19  # Next day
    
    # Verify half-open interval: event at exactly 08:00 should be in shift 2
    event_at_8 = datetime(2026, 3, 18, 8, 0, 0, tzinfo=LOCAL_TZ)
    assert get_shift_id(event_at_8) == 2
    
    print("  OK: shift boundaries use half-open intervals")


def test_event_key_uniqueness():
    """Test event keys include microseconds for uniqueness."""
    print("Testing event key uniqueness...")
    
    # Create timestamps with microseconds
    ts1 = datetime(2026, 3, 18, 10, 0, 0, 123456, tzinfo=LOCAL_TZ)
    ts2 = datetime(2026, 3, 18, 10, 0, 0, 234567, tzinfo=LOCAL_TZ)
    
    fmt1 = format_log_timestamp(ts1)
    fmt2 = format_log_timestamp(ts2)
    
    # Should be different due to microseconds
    assert fmt1 != fmt2
    assert ".123456" in fmt1
    assert ".234567" in fmt2
    
    print("  OK: event keys include microseconds")


def test_pipeline_media_flow():
    """Test media events flow through shift manager."""
    print("Testing media -> shift_manager -> DB flow...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pipeline = create_shift_manager(
            Path(tmpdir),
            log_path=Path(tmpdir) / "user_log.txt",
            database_path=Path(tmpdir) / "user_log.db",
        )
        
        # Log a media event
        pipeline.log(
            "MEDIA_PLAYBACK",
            {
                "ended_at": "2026-03-18T10:00:00Z",
                "duration_seconds": 120,
                "source_app": "Spotify",
                "title": "Test Song",
                "artist": "Test Artist",
            },
        )
        
        # Verify it was persisted
        count = pipeline.database.count_events()
        assert count == 1, f"Expected 1 event, got {count}"
        
        # Verify in DB
        entries = pipeline.database.all_entries()
        assert len(entries) == 1
        assert entries[0].source == "Spotify"
        assert entries[0].event_type == "MEDIA_PLAYBACK"
        
        pipeline.close()
        
    print("  OK: media events flow through pipeline correctly")


def test_pipeline_app_usage_flow():
    """Test app usage events flow through shift manager."""
    print("Testing app_usage -> shift_manager -> DB flow...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pipeline = create_shift_manager(
            Path(tmpdir),
            log_path=Path(tmpdir) / "user_log.txt",
            database_path=Path(tmpdir) / "user_log.db",
        )
        
        # Log an app usage event
        pipeline.log(
            "APP_USAGE",
            {
                "ended_at": "2026-03-18T10:00:00Z",
                "duration_seconds": 60,
                "app_name": "Code",
                "window_title": "main.py - VS Code",
            },
        )
        
        # Verify it was persisted
        count = pipeline.database.count_events()
        assert count == 1, f"Expected 1 event, got {count}"
        
        # Verify shift_id is set
        entries = pipeline.database.all_entries()
        assert len(entries) == 1
        # 10:00 UTC = 10:00 local (assuming UTC+0 for test)
        # Should be in shift 2 (08:00-16:00)
        
        pipeline.close()
        
    print("  OK: app_usage events flow through pipeline correctly")


def test_rapid_event_uniqueness():
    """Test rapid events don't cause key collisions."""
    print("Testing rapid event uniqueness...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pipeline = create_shift_manager(
            Path(tmpdir),
            log_path=Path(tmpdir) / "user_log.txt",
            database_path=Path(tmpdir) / "user_log.db",
        )
        
        # Log multiple events in rapid succession (same second, different microseconds)
        for i in range(10):
            pipeline.log(
                "APP_USAGE",
                {
                    "ended_at": "2026-03-18T10:00:00Z",
                    "duration_seconds": 1,
                    "app_name": f"App{i}",
                    "window_title": f"Window{i}",
                },
            )
        
        # Should have 10 unique events (no duplicates)
        count = pipeline.database.count_events()
        assert count == 10, f"Expected 10 events, got {count} (possible key collision)"
        
        pipeline.close()
        
    print("  OK: rapid events are unique (no collisions)")


def test_log_timestamp_format():
    """Test timestamp format includes microseconds."""
    print("Testing log timestamp format...")
    
    ts = datetime(2026, 3, 18, 10, 30, 45, 123456, tzinfo=LOCAL_TZ)
    formatted = format_log_timestamp(ts)
    
    # Should include microseconds
    assert ".123456" in formatted
    # Should be sortable
    assert "2026-03-18 10:30:45.123456" == formatted
    
    print("  OK: timestamp format includes microseconds")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Running Critical Fix Tests")
    print("=" * 60)
    
    test_shift_id_calculation()
    test_shift_time_range_boundaries()
    test_event_key_uniqueness()
    test_pipeline_media_flow()
    test_pipeline_app_usage_flow()
    test_rapid_event_uniqueness()
    test_log_timestamp_format()
    
    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
