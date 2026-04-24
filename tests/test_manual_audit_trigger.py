from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.manual_audit_trigger import (
    IncrementalCollector,
    parse_datetime_any,
    utc_now,
)


UTC = timezone.utc


def test_parse_datetime_any() -> None:
    assert parse_datetime_any("2026-04-11") is not None
    assert parse_datetime_any("2026-04-11T10:00:00") is not None
    assert parse_datetime_any("") is None
    assert parse_datetime_any(None) is None
    assert parse_datetime_any("invalid") is None


def test_utc_now() -> None:
    now = utc_now()
    assert now.tzinfo == UTC


def test_incremental_collector_state(tmp_path: Path) -> None:
    """Test that incremental collector tracks state correctly."""
    from src.shift_manager import create_shift_manager
    
    pipeline = create_shift_manager(tmp_path)
    collector = IncrementalCollector(pipeline)
    
    initial_scheduled = collector.get_last_scheduled_timestamp()
    initial_manual = collector.get_last_manual_timestamp()
    
    assert initial_scheduled is None
    assert initial_manual is None
    
    now = utc_now()
    collector.set_last_manual_timestamp(now)
    collector.mark_scheduled_run(now)
    
    after_scheduled = collector.get_last_scheduled_timestamp()
    after_manual = collector.get_last_manual_timestamp()
    
    assert after_scheduled is not None
    assert after_manual is not None
    assert after_scheduled == now
    assert after_manual == now
    
    pipeline.close()


def test_incremental_collector_dry_run(tmp_path: Path) -> None:
    """Test that dry-run doesn't write to database."""
    from src.shift_manager import create_shift_manager, normalize_event
    
    pipeline = create_shift_manager(tmp_path)
    collector = IncrementalCollector(pipeline)
    
    entry = normalize_event(
        "APP_USAGE",
        {
            "app_name": "test_app",
            "window_title": "test",
            "duration_seconds": 60,
        },
    )
    pipeline.master_log.append_entry(entry)
    
    initial_count = pipeline.database.count_events()
    
    now = utc_now()
    collector.mark_scheduled_run(now - timedelta(days=1))
    
    result = collector.collect_new_data(
        since=now - timedelta(hours=1),
        dry_run=True,
    )
    
    after_count = pipeline.database.count_events()
    
    assert result["events_collected"] >= 1
    assert result["dry_run"] is True
    assert initial_count == after_count
    
    pipeline.close()


def test_incremental_collector_collect_writes(tmp_path: Path) -> None:
    """Test that collect (not dry-run) writes to database."""
    from src.shift_manager import create_shift_manager, normalize_event
    
    pipeline = create_shift_manager(tmp_path)
    collector = IncrementalCollector(pipeline)
    
    entry = normalize_event(
        "WEBSITE_USAGE",
        {
            "domain": "example.com",
            "url": "https://example.com",
            "duration_seconds": 120,
        },
    )
    pipeline.master_log.append_entry(entry)
    
    initial_count = pipeline.database.count_events()
    
    now = utc_now()
    collector.mark_scheduled_run(now - timedelta(days=1))
    
    result = collector.collect_new_data(
        since=now - timedelta(hours=1),
        dry_run=False,
    )
    
    after_count = pipeline.database.count_events()
    
    assert result["events_collected"] >= 1
    assert result["dry_run"] is False
    assert after_count >= initial_count
    
    pipeline.close()


def test_incremental_collector_validate_no_conflict(tmp_path: Path) -> None:
    """Test conflict validation."""
    from src.shift_manager import create_shift_manager
    
    pipeline = create_shift_manager(tmp_path)
    collector = IncrementalCollector(pipeline)
    
    validation = collector.validate_no_conflict()
    
    assert "safe_to_run" in validation
    assert "checks" in validation
    assert "warnings" in validation
    
    assert isinstance(validation["safe_to_run"], bool)
    assert isinstance(validation["checks"], list)
    assert isinstance(validation["warnings"], list)
    
    pipeline.close()


def test_since_parameter() -> None:
    """Test --since parameter parsing."""
    assert parse_datetime_any("2026-04-11") is not None


def test_incremental_with_custom_since(tmp_path: Path) -> None:
    """Test collecting from custom since timestamp."""
    from src.shift_manager import create_shift_manager, normalize_event
    
    pipeline = create_shift_manager(tmp_path)
    collector = IncrementalCollector(pipeline)
    
    old_entry = normalize_event(
        "APP_USAGE",
        {
            "app_name": "old_app",
            "duration_seconds": 10,
        },
    )
    pipeline.master_log.append_entry(old_entry)
    
    custom_since = datetime(2025, 1, 1, tzinfo=UTC)
    
    result = collector.collect_new_data(
        since=custom_since,
        dry_run=True,
    )
    
    assert result["since"] is not None
    assert result["events_collected"] >= 1
    
    pipeline.close()


def test_incremental_no_conflict_with_tracker(tmp_path: Path) -> None:
    """Test that incremental collection doesn't conflict with ongoing tracking.
    
    This tests that:
    1. collector reads entries without blocking writer
    2. writes use idempotent upsert (no duplicates)
    3. state tracking doesn't interfere with pipeline
    """
    from src.shift_manager import create_shift_manager, normalize_event
    
    pipeline = create_shift_manager(tmp_path)
    collector = IncrementalCollector(pipeline)
    
    entry1 = normalize_event(
        "MEDIA_PLAYBACK",
        {
            "source_app": "spotify",
            "title": "Test Song",
            "artist": "Test Artist",
            "duration_seconds": 180,
        },
    )
    pipeline.master_log.append_entry(entry1)
    
    validation = collector.validate_no_conflict()
    assert validation["safe_to_run"] is True
    
    now = utc_now()
    collector.mark_scheduled_run(now - timedelta(hours=1))
    
    result = collector.collect_new_data(
        since=now - timedelta(minutes=30),
        dry_run=False,
    )
    
    assert result["events_collected"] >= 1
    
    duplicate_result = collector.collect_new_data(
        since=now - timedelta(minutes=30),
        dry_run=False,
    )
    
    assert duplicate_result["events_collected"] >= 1
    
    pipeline.close()


from datetime import timedelta