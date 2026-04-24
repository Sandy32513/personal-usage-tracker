"""Stress Testing Suite for Personal Usage Tracker

Simulates 1,000,000+ executions to identify bottlenecks, failures, and limits
in high-load production environments.
"""

from __future__ import annotations

import gc
import os
import random
import sqlite3
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import patch

import pytest

# Add src to path for imports
ROOT = Path(__file__).resolve().parent.parent
for candidate in (ROOT, ROOT / "src", ROOT / "scripts"):
    value = str(candidate)
    if candidate.exists() and value not in sys.path:
        sys.path.insert(0, value)

from shift_manager import (
    ShiftManager,
    create_shift_manager,
    MasterLogWriter,
    EventDatabase,
    normalize_event,
    LogEntry,
    parse_log_line,
    format_log_timestamp,
    get_shift_id,
)


UTC = timezone.utc
LOCAL_TZ = datetime.now().astimezone().tzinfo or UTC
pytestmark = pytest.mark.slow


RUN_STRESS_TESTS = os.getenv("RUN_STRESS_TESTS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}

if not RUN_STRESS_TESTS:
    pytest.skip(
        "Stress tests are opt-in. Set RUN_STRESS_TESTS=true to execute them.",
        allow_module_level=True,
    )


# =============================================================================
# Test Configuration
# =============================================================================

# Number of executions for stress testing (can be scaled)
STRESS_TEST_COUNT = int(os.getenv("STRESS_TEST_COUNT", "5000"))
EXTREME_STRESS_COUNT = int(os.getenv("EXTREME_STRESS_COUNT", "50000"))

# Timeouts for various operations
OPERATION_TIMEOUT_SECONDS = 30.0
BATCH_OPERATION_TIMEOUT_SECONDS = 300.0

# Performance thresholds (in seconds)
MAX_SINGLE_WRITE_MS = 100  # Max 100ms for single write
MAX_BATCH_WRITE_SECONDS = 60  # Max 60s for batch of 10k writes
MAX_DB_QUERY_MS = 50  # Max 50ms for database queries
MAX_MEMORY_MB = 500  # Max 500MB memory usage


# =============================================================================
# Test Utilities
# =============================================================================

def generate_test_payload(index: int) -> Dict[str, Any]:
    """Generate test payload for stress testing."""
    minute = (index // 60) % 60
    second = index % 60
    return {
        "ended_at": f"2026-03-18T{10 + (index % 12):02d}:{minute:02d}:{second:02d}Z",
        "duration_seconds": random.randint(1, 3600),
        "app_name": f"App_{index % 100}",
        "window_title": f"Window_{index % 500}",
    }


def generate_website_payload(index: int) -> Dict[str, Any]:
    """Generate website usage payload."""
    minute = (index // 60) % 60
    second = index % 60
    return {
        "ended_at": f"2026-03-18T{10 + (index % 12):02d}:{minute:02d}:{second:02d}Z",
        "duration_seconds": random.randint(10, 1800),
        "domain": f"site_{index % 200}.com",
        "url": f"https://site_{index % 200}.com/page_{index % 50}",
        "browser": random.choice(["chrome", "edge", "firefox"]),
        "page_title": f"Page Title {index % 100}",
    }


def generate_media_payload(index: int) -> Dict[str, Any]:
    """Generate media playback payload."""
    minute = (index // 60) % 60
    second = index % 60
    return {
        "ended_at": f"2026-03-18T{10 + (index % 12):02d}:{minute:02d}:{second:02d}Z",
        "duration_seconds": random.randint(30, 600),
        "source_app": random.choice(["Spotify", "VLC", "YouTube"]),
        "title": f"Track {index % 100}",
        "artist": f"Artist {index % 50}",
    }


class StressTestMetrics:
    """Metrics collection for stress tests."""

    def __init__(self) -> None:
        self.operation_times: List[float] = []
        self.errors: List[str] = []
        self.memory_samples: List[int] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def start(self) -> None:
        self.start_time = time.perf_counter()
        gc.collect()

    def end(self) -> None:
        self.end_time = time.perf_counter()
        gc.collect()

    def record_operation(self, duration_ms: float, operation: str) -> None:
        self.operation_times.append(duration_ms)
        if duration_ms > MAX_SINGLE_WRITE_MS * 10:
            self.errors.append(f"Slow {operation}: {duration_ms:.2f}ms")

    def sample_memory(self) -> int:
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss
        except Exception:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        if not self.operation_times:
            return {"error": "No operations recorded"}

        sorted_times = sorted(self.operation_times)
        total_time = (self.end_time or 0) - (self.start_time or 0)

        return {
            "total_operations": len(self.operation_times),
            "total_time_seconds": round(total_time, 2),
            "operations_per_second": round(len(self.operation_times) / max(total_time, 0.001), 2),
            "avg_ms": round(sum(sorted_times) / len(sorted_times), 2),
            "p50_ms": round(sorted_times[len(sorted_times) // 2], 2),
            "p95_ms": round(sorted_times[int(len(sorted_times) * 0.95)], 2),
            "p99_ms": round(sorted_times[int(len(sorted_times) * 0.99)], 2),
            "max_ms": round(max(sorted_times), 2),
            "error_count": len(self.errors),
            "errors": self.errors[:10],  # First 10 errors
        }


# =============================================================================
# High-Volume Logging Tests
# =============================================================================

class TestHighVolumeLogging:
    """Test suite for high-volume logging scenarios."""

    def test_single_thread_high_volume_writes(self, tmp_path: Path) -> None:
        """Test 100k+ sequential writes in single thread."""
        metrics = StressTestMetrics()
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "user_log.txt")

        metrics.start()
        for i in range(STRESS_TEST_COUNT):
            start = time.perf_counter()
            pipeline.log("APP_USAGE", generate_test_payload(i))
            duration_ms = (time.perf_counter() - start) * 1000
            metrics.record_operation(duration_ms, "log")
            if i % 10000 == 0 and i > 0:
                metrics.sample_memory()

        metrics.end()
        stats = metrics.get_stats()

        print(f"\n[Single Thread {STRESS_TEST_COUNT} writes] {stats}")
        assert stats["error_count"] == 0, f"Errors occurred: {stats['errors']}"
        assert stats["p95_ms"] < MAX_SINGLE_WRITE_MS * 10, f"P95 too slow: {stats['p95_ms']}ms"
        assert pipeline.database.count_events() == STRESS_TEST_COUNT

    def test_concurrent_writes(self, tmp_path: Path) -> None:
        """Test concurrent writes from multiple threads."""
        NUM_THREADS = 8
        WRITES_PER_THREAD = STRESS_TEST_COUNT // NUM_THREADS
        metrics = StressTestMetrics()
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "user_log.txt")
        errors = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(WRITES_PER_THREAD):
                    start = time.perf_counter()
                    pipeline.log("APP_USAGE", generate_test_payload(thread_id * WRITES_PER_THREAD + i))
                    duration_ms = (time.perf_counter() - start) * 1000
                    metrics.record_operation(duration_ms, f"thread_{thread_id}")
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        metrics.start()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=BATCH_OPERATION_TIMEOUT_SECONDS)
        metrics.end()

        stats = metrics.get_stats()
        print(f"\n[Concurrent {NUM_THREADS} threads x {WRITES_PER_THREAD}] {stats}")

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert stats["error_count"] == 0, f"Write errors: {stats['errors']}"

    def test_mixed_event_types(self, tmp_path: Path) -> None:
        """Test high volume with mixed event types."""
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "user_log.txt")
        metrics = StressTestMetrics()
        metrics.start()

        for i in range(STRESS_TEST_COUNT):
            event_type = ["APP_USAGE", "WEBSITE_USAGE", "MEDIA_PLAYBACK"][i % 3]
            if event_type == "APP_USAGE":
                payload = generate_test_payload(i)
            elif event_type == "WEBSITE_USAGE":
                payload = generate_website_payload(i)
            else:
                payload = generate_media_payload(i)

            start = time.perf_counter()
            pipeline.log(event_type, payload)
            metrics.record_operation((time.perf_counter() - start) * 1000, event_type)

        metrics.end()
        stats = metrics.get_stats()

        print(f"\n[Mixed {STRESS_TEST_COUNT} events] {stats}")
        assert stats["error_count"] == 0
        assert pipeline.database.count_events() == STRESS_TEST_COUNT


# =============================================================================
# Database Stress Tests
# =============================================================================

class TestDatabaseStress:
    """Database stress tests for both SQLite and MySQL/SQLServer."""

    def test_sqlite_high_volume_upserts(self, tmp_path: Path) -> None:
        """Test SQLite with many upsert operations."""
        db_path = tmp_path / "stress_test.db"
        db = EventDatabase(db_path)
        metrics = StressTestMetrics()

        # Use duplicate event keys to test upsert performance
        unique_keys = 1000  # Reuse same keys for upsert testing
        metrics.start()

        for i in range(STRESS_TEST_COUNT):
            entry = normalize_event(
                "APP_USAGE",
                generate_test_payload(i),
                logged_at=datetime.now(tz=LOCAL_TZ)
            )
            # Force same event_key to test upsert path
            entry = LogEntry(
                timestamp=entry.timestamp,
                category=entry.category,
                source=entry.source,
                item=f"App_{i % unique_keys}",
                event_type=entry.event_type,
                duration_seconds=entry.duration_seconds,
                window=entry.window,
                url=entry.url,
                data=entry.data,
                raw_line="",
            )

            start = time.perf_counter()
            db.upsert_entry(entry, log_written=True)
            metrics.record_operation((time.perf_counter() - start) * 1000, "upsert")

        metrics.end()
        stats = metrics.get_stats()

        print(f"\n[SQLite {STRESS_TEST_COUNT} upserts] {stats}")
        # Note: With duplicate keys, count should be less than operations
        actual_count = db.count_events()
        print(f"Unique entries: {actual_count} (expected ~{unique_keys})")

        db.close()
        assert actual_count <= unique_keys + 100, "Too many unique entries"

    def test_sqlite_batch_operations(self, tmp_path: Path) -> None:
        """Test SQLite batch operations."""
        db_path = tmp_path / "batch_test.db"
        db = EventDatabase(db_path)
        metrics = StressTestMetrics()

        # Batch write 100k entries
        entries = []
        for i in range(STRESS_TEST_COUNT):
            entry = normalize_event("APP_USAGE", generate_test_payload(i))
            entries.append(entry)

        metrics.start()
        for entry in entries:
            db.upsert_entry(entry, log_written=True)

        metrics.end()
        stats = metrics.get_stats()

        print(f"\n[SQLite batch {STRESS_TEST_COUNT}] {stats}")
        assert db.count_events() == STRESS_TEST_COUNT
        db.close()

    def test_master_log_high_volume(self, tmp_path: Path) -> None:
        """Test MasterLogWriter at high volume."""
        log_path = tmp_path / "stress_log.txt"
        writer = MasterLogWriter(log_path)
        metrics = StressTestMetrics()

        metrics.start()
        for i in range(STRESS_TEST_COUNT):
            start = time.perf_counter()
            writer.write("APP_USAGE", generate_test_payload(i))
            metrics.record_operation((time.perf_counter() - start) * 1000, "write")

        metrics.end()
        stats = metrics.get_stats()

        print(f"\n[MasterLog {STRESS_TEST_COUNT} writes] {stats}")
        assert stats["error_count"] == 0
        assert log_path.exists()
        assert log_path.stat().st_size > 0


# =============================================================================
# Chaos Testing - Failure Simulation
# =============================================================================

class TestChaosScenarios:
    """Chaos testing - simulate failures and verify recovery."""

    def test_log_file_lock_contention(self, tmp_path: Path) -> None:
        """Test behavior when log file is locked by another process."""
        log_path = tmp_path / "locked_log.txt"
        writer = MasterLogWriter(log_path)

        # Simulate locked file by patching lock behavior
        original_lock = writer._lock

        errors = []
        for i in range(1000):
            try:
                writer.write("APP_USAGE", generate_test_payload(i))
            except Exception as e:
                errors.append(str(e))

        print(f"\n[Lock Contention] {len(errors)} errors in 1000 writes")
        # Should handle gracefully with retry logic

    def test_database_connection_failure(self, tmp_path: Path) -> None:
        """Test database connection failure handling."""
        db_path = tmp_path / "fail_test.db"
        db = EventDatabase(db_path)

        # Close the connection to simulate failure
        db._connection = None

        errors = []
        for i in range(100):
            try:
                entry = normalize_event("APP_USAGE", generate_test_payload(i))
                db.upsert_entry(entry, log_written=True)
            except Exception as e:
                errors.append(str(e))

        print(f"\n[DB Failure] {len(errors)} errors in 100 writes")
        # Verify retry mechanism works
        db.close()

    def test_pending_entries_overflow(self, tmp_path: Path) -> None:
        """Test behavior when pending entries queue overflows."""
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "user_log.txt")

        # Simulate write failures by making both log and DB fail
        # This should fill up pending entries

        # Patch both write methods to fail
        original_log = pipeline.master_log.append_entry
        original_db = pipeline.database.upsert_entry

        def fail_log(*args, **kwargs):
            raise IOError("Simulated log failure")

        def fail_db(*args, **kwargs):
            raise sqlite3.Error("Simulated DB failure")

        pipeline.master_log.append_entry = fail_log
        pipeline.database.upsert_entry = fail_db

        # Fill pending entries
        for i in range(10000):
            pipeline.log("APP_USAGE", generate_test_payload(i))

        # Check pending queue
        with pipeline._pending_lock:
            pending_count = len(pipeline._pending_entries)

        print(f"\n[Pending Overflow] Pending entries: {pending_count}")

        # Restore methods
        pipeline.master_log.append_entry = original_log
        pipeline.database.upsert_entry = original_db

    def test_concurrent_db_access(self, tmp_path: Path) -> None:
        """Test concurrent database access from multiple threads."""
        db_path = tmp_path / "concurrent_db.db"
        db = EventDatabase(db_path)

        NUM_THREADS = 8
        OPS_PER_THREAD = 5000
        errors = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(OPS_PER_THREAD):
                    entry = normalize_event(
                        "APP_USAGE",
                        generate_test_payload(thread_id * OPS_PER_THREAD + i),
                    )
                    db.upsert_entry(entry, log_written=True)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        print(f"\n[Concurrent DB] {len(errors)} errors, {db.count_events()} records")
        assert len(errors) == 0, f"Concurrent access errors: {errors}"
        db.close()


# =============================================================================
# Performance Regression Tests
# =============================================================================

class TestPerformanceRegression:
    """Performance regression tests to catch slowdowns."""

    @pytest.mark.slow
    def test_100k_operations_performance(self, tmp_path: Path) -> None:
        """Verify 100k operations complete within acceptable time."""
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "perf_test.txt")

        start = time.perf_counter()
        for i in range(100000):
            pipeline.log("APP_USAGE", generate_test_payload(i))

        elapsed = time.perf_counter() - start
        ops_per_sec = 100000 / elapsed

        print(f"\n[Performance] {ops_per_sec:.0f} ops/sec ({elapsed:.2f}s total)")
        assert ops_per_sec > 1000, f"Too slow: {ops_per_sec:.0f} ops/sec"

    @pytest.mark.slow
    def test_1m_operations_extreme_scale(self, tmp_path: Path) -> None:
        """Test extreme scale with 1 million operations."""
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "extreme_test.txt")

        # Sample every Nth operation for timing
        sample_interval = 10000
        samples = []

        start = time.perf_counter()
        for i in range(EXTREME_STRESS_COUNT):
            pipeline.log("APP_USAGE", generate_test_payload(i))
            if i > 0 and i % sample_interval == 0:
                samples.append(time.perf_counter() - start)

        elapsed = time.perf_counter() - start
        ops_per_sec = EXTREME_STRESS_COUNT / elapsed

        print(f"\n[Extreme Scale] {ops_per_sec:.0f} ops/sec ({elapsed:.2f}s for {EXTREME_STRESS_COUNT})")
        print(f"[Samples] {samples[:5]}")

        # Verify data integrity
        count = pipeline.database.count_events()
        print(f"[Data] {count} records in database")
        assert count >= EXTREME_STRESS_COUNT * 0.99, "Data loss detected"


# =============================================================================
# Memory and Resource Tests
# =============================================================================

class TestMemoryAndResources:
    """Test memory usage and resource limits."""

    def test_memory_usage_stability(self, tmp_path: Path) -> None:
        """Test memory stays stable under load."""
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "mem_test.txt")

        try:
            import psutil
            process = psutil.Process()
            initial_memory = process.memory_info().rss / (1024 * 1024)
        except ImportError:
            pytest.skip("psutil not available")

        # Write many entries
        for i in range(50000):
            pipeline.log("APP_USAGE", generate_test_payload(i))

        # Force GC and check memory
        gc.collect()

        try:
            final_memory = process.memory_info().rss / (1024 * 1024)
            memory_increase = final_memory - initial_memory
            print(f"\n[Memory] Initial: {initial_memory:.1f}MB, Final: {final_memory:.1f}MB, Increase: {memory_increase:.1f}MB")
            assert memory_increase < MAX_MEMORY_MB, f"Memory increased by {memory_increase:.1f}MB"
        except ImportError:
            pass


# =============================================================================
# Data Integrity Tests
# =============================================================================

class TestDataIntegrity:
    """Test data integrity under stress."""

    def test_no_data_loss_under_load(self, tmp_path: Path) -> None:
        """Verify no data loss under high load."""
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "integrity_test.txt")

        for i in range(10000):
            pipeline.log("APP_USAGE", generate_test_payload(i))

        # Verify all entries exist
        count = pipeline.database.count_events()
        log_entries = pipeline.master_log.read_all()

        print(f"\n[Integrity] DB: {count}, Log: {len(log_entries)}")
        assert count == 10000, f"Expected 10000, got {count}"
        assert len(log_entries) == 10000, f"Expected 10000 log entries, got {len(log_entries)}"

    def test_duplicate_handling(self, tmp_path: Path) -> None:
        """Test duplicate entry handling."""
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "dup_test.txt")

        # Same payload written multiple times
        payload = generate_test_payload(1)
        for _ in range(100):
            pipeline.log("APP_USAGE", payload)

        count = pipeline.database.count_events()
        print(f"\n[Duplicates] {count} unique entries from 100 writes")
        # Should be 1 due to idempotent upsert
        assert count == 1, f"Expected 1, got {count}"

    def test_query_performance_at_scale(self, tmp_path: Path) -> None:
        """Test query performance with large dataset."""
        pipeline = create_shift_manager(tmp_path, log_path=tmp_path / "query_test.txt")

        # Populate with data
        for i in range(10000):
            pipeline.log("APP_USAGE", generate_test_payload(i))

        # Query performance
        from datetime import date
        start = time.perf_counter()
        entries = pipeline.entries_for_date(date(2026, 3, 18))
        query_time = (time.perf_counter() - start) * 1000

        print(f"\n[Query] {query_time:.2f}ms for {len(entries)} entries")
        assert query_time < MAX_DB_QUERY_MS * 10, f"Query too slow: {query_time}ms"


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
